from datetime import datetime
from functools import lru_cache
import io
import logging
import math
from typing import Any
import uuid

import joblib
from sqlalchemy.orm import Session

from ..config import settings
from ..models import HourlyWeather, JobRun, ModelArtifact, ModelVersion


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
logger = logging.getLogger(__name__)
_model_object_cache: dict[int, object] = {}


@lru_cache(maxsize=1)
def _import_pandas():
    import pandas as pd

    return pd


@lru_cache(maxsize=1)
def _import_sklearn_modules():
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    return RandomForestRegressor, mean_absolute_error, mean_squared_error, r2_score


@lru_cache(maxsize=1)
def _import_mlflow_modules():
    import mlflow
    import mlflow.sklearn as mlflow_sklearn

    return mlflow, mlflow_sklearn


def _to_frame(rows: list[HourlyWeather]):
    pd = _import_pandas()
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


def _prepare_dataset(db: Session):
    rows = (
        db.query(HourlyWeather)
        .filter(HourlyWeather.temperature_c.isnot(None))
        .order_by(HourlyWeather.timestamp.desc())
        .limit(settings.model_training_max_rows)
        .all()
    )
    rows.reverse()

    frame = _to_frame(rows)
    if frame.empty:
        return frame

    frame = frame.dropna(subset=[TARGET_COLUMN])
    return frame


def _build_feature_defaults(frame: Any) -> dict[str, float]:
    pd = _import_pandas()
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


@lru_cache(maxsize=1)
def _load_model_cached(model_uri: str, tracking_uri: str):
    mlflow, mlflow_sklearn = _import_mlflow_modules()
    mlflow.set_tracking_uri(tracking_uri)
    return mlflow_sklearn.load_model(model_uri)


def _clear_inference_caches() -> None:
    _load_model_cached.cache_clear()
    _model_object_cache.clear()


def _set_model_cache(version_id: int, model: object) -> None:
    _model_object_cache.clear()
    _model_object_cache[version_id] = model


def _serialize_model(model: object) -> bytes:
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return buffer.getvalue()


def _deserialize_model(payload: bytes) -> object:
    return joblib.load(io.BytesIO(payload))


def _upsert_model_artifact(db: Session, model_version_id: int, model: object) -> None:
    payload = _serialize_model(model)
    existing = (
        db.query(ModelArtifact)
        .filter(ModelArtifact.model_version_id == model_version_id)
        .first()
    )
    if existing is None:
        db.add(
            ModelArtifact(
                model_version_id=model_version_id,
                artifact_format="joblib",
                artifact_bytes=payload,
            )
        )
        return

    existing.artifact_format = "joblib"
    existing.artifact_bytes = payload


def _load_model_for_version(db: Session, version: ModelVersion) -> object | None:
    if version.id in _model_object_cache:
        return _model_object_cache[version.id]

    artifact = (
        db.query(ModelArtifact)
        .filter(ModelArtifact.model_version_id == version.id)
        .order_by(ModelArtifact.created_at.desc())
        .first()
    )
    if artifact is not None:
        try:
            model = _deserialize_model(artifact.artifact_bytes)
            _set_model_cache(version.id, model)
            return model
        except Exception as exc:
            logger.warning(
                "Failed loading DB artifact for model version id=%s: %s",
                version.id,
                exc,
            )

    try:
        model = _load_model_cached(version.model_uri, settings.mlflow_tracking_uri)
        _set_model_cache(version.id, model)
        return model
    except Exception:
        _load_model_cached.cache_clear()
        return None


def _is_model_version_loadable(db: Session, version: ModelVersion) -> bool:
    model = _load_model_for_version(db, version)
    if model is not None:
        return True

    logger.warning(
        "Model version id=%s uri=%s is not loadable",
        version.id,
        version.model_uri,
    )
    return False


def _get_inference_model_bundle(db: Session) -> tuple[ModelVersion, object] | None:
    active = get_active_model_version(db)
    if active is not None:
        model = _load_model_for_version(db, active)
        if model is not None:
            return active, model

    if active is not None:
        logger.warning(
            "Active model version id=%s is unavailable for inference; searching fallback versions",
            active.id,
        )

    base_query = db.query(ModelVersion).filter(ModelVersion.model_name == settings.mlflow_model_name)
    if active is not None:
        base_query = base_query.filter(ModelVersion.id != active.id)

    candidates = (
        base_query.filter(ModelVersion.status == "candidate")
        .order_by(ModelVersion.created_at.desc())
        .all()
    )
    for candidate in candidates:
        model = _load_model_for_version(db, candidate)
        if model is not None:
            logger.warning(
                "Using fallback candidate model version id=%s for inference",
                candidate.id,
            )
            return candidate, model

    others = (
        base_query.filter(ModelVersion.status != "candidate")
        .order_by(ModelVersion.created_at.desc())
        .all()
    )
    for version in others:
        model = _load_model_for_version(db, version)
        if model is not None:
            logger.warning(
                "Using fallback model version id=%s with status=%s for inference",
                version.id,
                version.status,
            )
            return version, model

    return None


def _build_inference_feature_defaults(active: ModelVersion) -> dict[str, float]:
    defaults: dict[str, float] = {}
    if active.params and isinstance(active.params.get("feature_defaults"), dict):
        defaults = {
            key: float(value)
            for key, value in active.params["feature_defaults"].items()
            if key in FEATURE_COLUMNS
        }

    for column in FEATURE_COLUMNS:
        defaults.setdefault(column, 0.0)
    return defaults


def _promote_if_better(db: Session, candidate: ModelVersion) -> bool:
    active = get_active_model_version(db)
    candidate_rmse = (candidate.metrics or {}).get("rmse")

    if active is None:
        candidate.status = "active"
        candidate.promoted_at = datetime.utcnow()
        _clear_inference_caches()
        return True

    if not _is_model_version_loadable(db, active):
        active.status = "archived"
        candidate.status = "active"
        candidate.promoted_at = datetime.utcnow()
        _clear_inference_caches()
        return True

    active_rmse = (active.metrics or {}).get("rmse")
    if active_rmse is None or candidate_rmse is None:
        return False

    if candidate_rmse <= active_rmse * settings.model_promote_rmse_margin:
        active.status = "archived"
        candidate.status = "active"
        candidate.promoted_at = datetime.utcnow()
        _clear_inference_caches()
        return True

    return False


def train_temperature_model(db: Session) -> dict:
    job = JobRun(job_name="model_training", status="running")
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        frame = _prepare_dataset(db)
        total_rows = int(len(frame))
        if frame.empty:
            raise ValueError("No weather rows available to train model")

        if total_rows < settings.model_min_training_rows:
            if total_rows < settings.model_bootstrap_min_rows:
                raise ValueError(
                    "Not enough data to train model "
                    f"(required >= {settings.model_bootstrap_min_rows} for bootstrap mode, got {total_rows})"
                )
            logger.warning(
                "Bootstrapping model with %s rows below configured minimum %s",
                total_rows,
                settings.model_min_training_rows,
            )

        if total_rows < 8:
            raise ValueError(
                f"Not enough data to train model split (need >= 8 rows, got {total_rows})"
            )

        split_idx = int(total_rows * 0.8)
        if split_idx < 1 or split_idx >= total_rows:
            split_idx = max(1, min(total_rows - 1, split_idx))
        train_frame = frame.iloc[:split_idx].copy()
        test_frame = frame.iloc[split_idx:].copy()

        defaults = _build_feature_defaults(train_frame)

        x_train = train_frame[FEATURE_COLUMNS].fillna(defaults)
        y_train = train_frame[TARGET_COLUMN]
        x_test = test_frame[FEATURE_COLUMNS].fillna(defaults)
        y_test = test_frame[TARGET_COLUMN]

        RandomForestRegressor, mean_absolute_error, mean_squared_error, r2_score = _import_sklearn_modules()
        model = RandomForestRegressor(
            n_estimators=settings.model_rf_n_estimators,
            random_state=42,
            min_samples_leaf=settings.model_rf_min_samples_leaf,
            max_depth=settings.model_rf_max_depth,
            n_jobs=settings.model_rf_n_jobs,
        )
        model.fit(x_train, y_train)
        preds = model.predict(x_test)

        rmse = float(mean_squared_error(y_test, preds, squared=False))
        mae = float(mean_absolute_error(y_test, preds))
        r2 = float(r2_score(y_test, preds)) if len(test_frame) > 1 else 0.0

        params = {
            "model_type": "RandomForestRegressor",
            "n_estimators": settings.model_rf_n_estimators,
            "min_samples_leaf": settings.model_rf_min_samples_leaf,
            "max_depth": settings.model_rf_max_depth,
            "n_jobs": settings.model_rf_n_jobs,
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

        run_id = uuid.uuid4().hex
        model_uri = f"db://model_versions/{run_id}"
        try:
            mlflow, mlflow_sklearn = _import_mlflow_modules()
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
                mlflow_sklearn.log_model(model, artifact_path="model")

                run_id = run.info.run_id
                model_uri = f"runs:/{run_id}/model"
        except Exception as exc:
            logger.warning("MLflow logging failed; continuing with DB artifact only: %s", exc)

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
        _upsert_model_artifact(db, row.id, model)
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


def get_inference_model_rmse(db: Session) -> float | None:
    bundle = _get_inference_model_bundle(db)
    if bundle is None:
        return None
    version, _ = bundle
    metrics = version.metrics or {}
    rmse_value = metrics.get("rmse")
    if rmse_value is None:
        return None
    try:
        return float(rmse_value)
    except (TypeError, ValueError):
        return None


def _coerce_feature_value(raw_value: object, default: float) -> float:
    if raw_value is None:
        return default
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def _build_feature_row_from_weather(row: HourlyWeather, defaults: dict[str, float]) -> list[float]:
    payload = {
        "hour": row.timestamp.hour,
        "day_of_year": row.timestamp.timetuple().tm_yday,
        "is_weekend": 1 if row.timestamp.weekday() >= 5 else 0,
        "temperature_c": row.temperature_c,
        "apparent_temperature_c": row.apparent_temperature_c,
        "precipitation_mm": row.precipitation_mm,
        "relative_humidity": row.relative_humidity,
        "wind_speed_kph": row.wind_speed_kph,
        "pressure_hpa": row.pressure_hpa,
        "cloud_cover": row.cloud_cover,
    }
    return [
        _coerce_feature_value(payload.get(column), defaults.get(column, 0.0))
        for column in FEATURE_COLUMNS
    ]


def predict_next_hour_temperature(db: Session, location_id: int) -> float | None:
    model_bundle = _get_inference_model_bundle(db)
    if model_bundle is None:
        return None
    active, model = model_bundle

    latest = (
        db.query(HourlyWeather)
        .filter(HourlyWeather.location_id == location_id)
        .order_by(HourlyWeather.timestamp.desc())
        .first()
    )
    if latest is None:
        return None

    base_defaults = _build_inference_feature_defaults(active)

    try:
        features = _build_feature_row_from_weather(latest, base_defaults)
        prediction = model.predict([features])[0]
        return float(prediction)
    except Exception as exc:
        # Active model metadata can drift from local MLflow artifacts across environments.
        # Fail soft so overview endpoints keep working even when model artifacts are unavailable.
        logger.exception("Custom model prediction failed for location_id=%s: %s", location_id, exc)
        _model_object_cache.clear()
        _load_model_cached.cache_clear()
        return None


def predict_hourly_temperature_series(
    db: Session, rows: list[HourlyWeather]
) -> list[float | None]:
    if not rows:
        return []

    model_bundle = _get_inference_model_bundle(db)
    if model_bundle is None:
        return [None] * len(rows)
    active, model = model_bundle

    base_defaults = _build_inference_feature_defaults(active)

    try:
        feature_rows = [_build_feature_row_from_weather(row, base_defaults) for row in rows]
        predictions = model.predict(feature_rows)
        return [float(value) for value in predictions]
    except Exception as exc:
        logger.exception("Custom model hourly series prediction failed: %s", exc)
        _model_object_cache.clear()
        _load_model_cached.cache_clear()
        return [None] * len(rows)
