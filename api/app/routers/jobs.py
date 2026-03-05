from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..schemas import JobRunResponse, ModelTrainResponse
from ..services.model_workflow import train_temperature_model
from ..services.orchestration import run_hourly_pipeline

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


def _authorize_scheduler(x_job_token: str | None) -> None:
    if x_job_token != settings.scheduler_job_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid scheduler token",
        )


@router.post("/run-hourly", response_model=JobRunResponse)
def run_hourly_job(
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> JobRunResponse:
    _authorize_scheduler(x_job_token)
    result = run_hourly_pipeline(db)
    return JobRunResponse(**result)


@router.post("/train-model", response_model=ModelTrainResponse)
def train_model_job(
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ModelTrainResponse:
    _authorize_scheduler(x_job_token)
    result = train_temperature_model(db)
    return ModelTrainResponse(**result)
