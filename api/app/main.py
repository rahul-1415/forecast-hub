import logging
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, SessionLocal, engine
from .routers.dashboard import router as dashboard_router
from .routers.health import router as health_router
from .routers.jobs import router as jobs_router
from .routers.models import router as models_router
from .routers.notifications import router as notifications_router
from .services.location import ensure_default_location
from .services.notifications import start_notification_scheduler, stop_notification_scheduler

logger = logging.getLogger(__name__)
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.db_ready = False
app.state.db_init_error = None
app.state.db_target = None


def _redact_db_url(url: str) -> str:
    # Hide credentials in URLs like postgresql://user:password@host/db
    return re.sub(r"(postgres(?:ql)?(?:\+psycopg)?://[^:]+:)([^@]+)(@)", r"\1***\3", url)


@app.on_event("startup")
def startup() -> None:
    db_ready = False
    app.state.db_init_error = None
    app.state.db_target = _redact_db_url(settings.sqlalchemy_database_url)
    try:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            ensure_default_location(db)
        finally:
            db.close()
        db_ready = True
    except Exception as exc:
        # Do not crash process on transient DB outages/quota blocks; keep service alive.
        logger.exception("Database initialization failed during startup: %s", exc)
        app.state.db_init_error = str(exc)

    app.state.db_ready = db_ready
    if db_ready:
        start_notification_scheduler()
    else:
        logger.warning("Skipping notification scheduler startup because database is unavailable.")


@app.on_event("shutdown")
def shutdown() -> None:
    stop_notification_scheduler()


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "environment": settings.environment,
        "docs": "/docs",
    }


app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(jobs_router)
app.include_router(models_router)
app.include_router(notifications_router)
