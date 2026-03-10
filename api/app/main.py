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

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_location(db)
    finally:
        db.close()
    start_notification_scheduler()


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
