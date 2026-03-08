from datetime import datetime
from functools import lru_cache

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sqlalchemy.orm import Session

from ..config import settings
from ..models import HourlyWeather, JobRun, ModelVersion


FEATURE_COLUMNS = [
    "hour",
    "day_of_year",
    "is_weekend",
    "temperature_c",
    "apparent_temperature_c",
    "precipitation_mm",
    "relative_humidity",
    "wind_speed_kph",
    "pressure_hpa",
    "cloud_cover",
]
TARGET_COLUMN = "target_next_temperature_c"


def _to_frame(rows: list[HourlyWeather]) -> pd.DataFrame:
    payload = [
        {
            "location_id": row.location_id,
            "timestamp": row.timestamp,
            "temperature_c": row.temperature_c,
            "apparent_temperature_c": row.apparent_temperature_c,
            "precipitation_mm": row.precipitation_mm,
            "relative_humidity": row.relative_humidity,
            "wind_speed_kph": row.wind_speed_kph,
            "pressure_hpa": row.pressure_hpa,
            "cloud_cover": row.cloud_cover,
        }
        for row in rows
    ]

    frame = pd.DataFrame(payload)
    if frame.empty:
        return frame

    frame = frame.sort_values(["location_id", "timestamp"]).reset_index(drop=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["hour"] = frame["timestamp"].dt.hour
    frame["day_of_year"] = frame["timestamp"].dt.dayofyear
    frame["is_weekend"] = (frame["timestamp"].dt.weekday >= 5).astype(int)
    frame[TARGET_COLUMN] = frame.groupby("location_id")["temperature_c"].shift(-1)
    return frame


def _prepare_dataset(db: Session) -> pd.DataFrame:
    rows = (
        db.query(HourlyWeather)
        .filter(HourlyWeather.temperature_c.isnot(None))
        .order_by(HourlyWeather.timestamp.asc())
        .all()
    )

    frame = _to_frame(rows)
    if frame.empty:
        return frame

    frame = frame.dropna(subset=[TARGET_COLUMN])
    return frame


def _build_feature_defaults(frame: pd.DataFrame) -> dict[str, float]:
    defaults: dict[str, float] = {}
    for column in FEATURE_COLUMNS:
        median = frame[column].median(skipna=True)
        defaults[column] = float(median) if pd.notna(median) else 0.0
    return defaults


def get_active_model_version(db: Session) -> ModelVersion | None:
    return (
        db.query(ModelVersion)
        .filter(
            ModelVersion.model_name == settings.mlflow_model_name,
            ModelVersion.status == "active",
        )
        .order_by(ModelVersion.promoted_at.desc().nullslast(), ModelVersion.created_at.desc())
        .first()
    )


@lru_cache(maxsize=8)
def _load_model_cached(model_uri: str):
    return mlflow.sklearn.load_model(model_uri)


def _promote_if_better(db: Session, candidate: ModelVersion) -> bool:
    active = get_active_model_version(db)
    candidate_rmse = (candidate.metrics or {}).get("rmse")

    if active is None:
        candidate.status = "active"
        candidate.promoted_at = datetime.utcnow()
        _load_model_cached.cache_clear()
        return True

    active_rmse = (active.metrics or {}).get("rmse")
    if active_rmse is None or candidate_rmse is None:
        return False

    if candidate_rmse <= active_rmse * settings.model_promote_rmse_margin:
        active.status = "archived"
        candidate.status = "active"
        candidate.promoted_at = datetime.utcnow()
        _load_model_cached.cache_clear()
        return True

    return False


def train_temperature_model(db: Session) -> dict:
    job = JobRun(job_name="model_training", status="running")
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        frame = _prepare_dataset(db)
        if frame.empty or len(frame) < settings.model_min_training_rows:
            raise ValueError(
                f"Not enough data to train model (required >= {settings.model_min_training_rows}, got {len(frame)})"
            )

        split_idx = int(len(frame) * 0.8)
        train_frame = frame.iloc[:split_idx].copy()
        test_frame = frame.iloc[split_idx:].copy()

        defaults = _build_feature_defaults(train_frame)

        x_train = train_frame[FEATURE_COLUMNS].fillna(defaults)
        y_train = train_frame[TARGET_COLUMN]
        x_test = test_frame[FEATURE_COLUMNS].fillna(defaults)
        y_test = test_frame[TARGET_COLUMN]

        model = RandomForestRegressor(
            n_estimators=300,
            random_state=42,
            min_samples_leaf=2,
            n_jobs=-1,
        )
        model.fit(x_train, y_train)
        preds = model.predict(x_test)

        rmse = float(mean_squared_error(y_test, preds, squared=False))
        mae = float(mean_absolute_error(y_test, preds))
        r2 = float(r2_score(y_test, preds)) if len(test_frame) > 1 else 0.0

        params = {
            "model_type": "RandomForestRegressor",
            "n_estimators": 300,
            "min_samples_leaf": 2,
            "feature_defaults": defaults,
            "rows_train": int(len(train_frame)),
            "rows_test": int(len(test_frame)),
            "feature_columns": FEATURE_COLUMNS,
        }

        metrics = {
            "rmse": rmse,
            "mae": mae,
            "r2": r2,
        }

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment_name)

        with mlflow.start_run(run_name=f"{settings.mlflow_model_name}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}") as run:
            mlflow.log_params(
                {
                    "model_name": settings.mlflow_model_name,
                    "n_estimators": params["n_estimators"],
                    "min_samples_leaf": params["min_samples_leaf"],
                    "rows_train": params["rows_train"],
                    "rows_test": params["rows_test"],
                }
            )
            mlflow.log_metrics(metrics)
            mlflow.log_dict(defaults, artifact_file="feature_defaults.json")
            mlflow.log_dict({"feature_columns": FEATURE_COLUMNS}, artifact_file="feature_columns.json")
            mlflow.sklearn.log_model(model, artifact_path="model")

            run_id = run.info.run_id

        model_uri = f"runs:/{run_id}/model"
        row = ModelVersion(
            model_name=settings.mlflow_model_name,
            run_id=run_id,
            model_uri=model_uri,
            status="candidate",
            metrics=metrics,
            params=params,
            feature_columns=FEATURE_COLUMNS,
        )
        db.add(row)
        db.flush()

        promoted = _promote_if_better(db, row)
        db.commit()
        db.refresh(row)

        job.status = "success"
        job.finished_at = datetime.utcnow()
        job.message = f"Model training completed. version_id={row.id} promoted={promoted}"
        db.commit()

        return {
            "status": "success",
            "version_id": row.id,
            "run_id": row.run_id,
            "model_uri": row.model_uri,
            "metrics": metrics,
            "promoted": promoted,
            "message": "Model training completed",
        }
    except Exception as exc:
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        job.message = str(exc)
        db.commit()
        raise


def list_model_versions(db: Session, limit: int = 20) -> list[ModelVersion]:
    return (
        db.query(ModelVersion)
        .filter(ModelVersion.model_name == settings.mlflow_model_name)
        .order_by(ModelVersion.created_at.desc())
        .limit(limit)
        .all()
    )


def predict_next_hour_temperature(db: Session, location_id: int) -> float | None:
    active = get_active_model_version(db)
    if active is None:
        return None

    latest = (
        db.query(HourlyWeather)
        .filter(HourlyWeather.location_id == location_id)
        .order_by(HourlyWeather.timestamp.desc())
        .first()
    )
    if latest is None:
        return None

    base_defaults = {}
    if active.params and isinstance(active.params.get("feature_defaults"), dict):
        base_defaults = {
            key: float(value)
            for key, value in active.params["feature_defaults"].items()
            if key in FEATURE_COLUMNS
        }

    frame = pd.DataFrame(
        [
            {
                "hour": latest.timestamp.hour,
                "day_of_year": latest.timestamp.timetuple().tm_yday,
                "is_weekend": 1 if latest.timestamp.weekday() >= 5 else 0,
                "temperature_c": latest.temperature_c,
                "apparent_temperature_c": latest.apparent_temperature_c,
                "precipitation_mm": latest.precipitation_mm,
                "relative_humidity": latest.relative_humidity,
                "wind_speed_kph": latest.wind_speed_kph,
                "pressure_hpa": latest.pressure_hpa,
                "cloud_cover": latest.cloud_cover,
            }
        ]
    )

    frame = frame.fillna(base_defaults)
    if frame[FEATURE_COLUMNS].isnull().any().any():
        return None

    try:
        model = _load_model_cached(active.model_uri)
        prediction = model.predict(frame[FEATURE_COLUMNS])[0]
        return float(prediction)
    except Exception:
        # Active model metadata can drift from local MLflow artifacts across environments.
        # Fail soft so overview endpoints keep working even when model artifacts are unavailable.
        _load_model_cached.cache_clear()
        return None
