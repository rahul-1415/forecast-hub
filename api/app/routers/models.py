from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ModelVersionItem, ModelVersionsResponse
from ..services.model_workflow import get_active_model_version, list_model_versions

router = APIRouter(prefix="/v1/models", tags=["models"])


@router.get("/active", response_model=ModelVersionItem | None)
def get_active_model(db: Session = Depends(get_db)) -> ModelVersionItem | None:
    row = get_active_model_version(db)
    if row is None:
        return None
    return ModelVersionItem(
        id=row.id,
        model_name=row.model_name,
        run_id=row.run_id,
        model_uri=row.model_uri,
        status=row.status,
        metrics=row.metrics,
        created_at=row.created_at,
        promoted_at=row.promoted_at,
    )


@router.get("/versions", response_model=ModelVersionsResponse)
def get_model_versions(db: Session = Depends(get_db)) -> ModelVersionsResponse:
    rows = list_model_versions(db)
    return ModelVersionsResponse(
        items=[
            ModelVersionItem(
                id=row.id,
                model_name=row.model_name,
                run_id=row.run_id,
                model_uri=row.model_uri,
                status=row.status,
                metrics=row.metrics,
                created_at=row.created_at,
                promoted_at=row.promoted_at,
            )
            for row in rows
        ]
    )
