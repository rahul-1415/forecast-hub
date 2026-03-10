from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthcheck(request: Request) -> dict:
    db_ready = bool(getattr(request.app.state, "db_ready", False))
    return {
        "status": "ok" if db_ready else "degraded",
        "database": "ok" if db_ready else "unavailable",
        "timestamp": datetime.utcnow().isoformat(),
    }
