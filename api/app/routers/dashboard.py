from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Location
from ..schemas import (
    AnomaliesResponse,
    AnomalyItem,
    HealthResponse,
    LocationRead,
    OutfitResponse,
    OverviewResponse,
    OverviewStats,
    PlanResponse,
    PlanWindowItem,
)
from ..services.anomalies import detect_anomalies, list_anomalies
from ..services.features import get_hours_between
from ..services.health import get_or_generate_health_alert
from ..services.ingestion import ingest_hourly_forecast
from ..services.llm import summarize_section
from ..services.location import get_or_create_location
from ..services.model_workflow import predict_next_hour_temperature
from ..services.orchestration import count_recent_anomalies
from ..services.outfit import get_or_generate_outfit
from ..services.plan import get_plan_windows

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


def _location_read(location: Location) -> LocationRead:
    return LocationRead(
        id=location.id,
        name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        timezone=location.timezone,
    )


def _resolve_location(db: Session, location_name: str) -> Location:
    return get_or_create_location(db, location_name)


def _ensure_hourly_data(db: Session, location: Location) -> None:
    now = datetime.utcnow()
    next_24 = get_hours_between(db, location.id, now, now + timedelta(hours=24))
    if next_24:
        return
    ingest_hourly_forecast(db, location)


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    location: str = Query(default=settings.default_location_name),
    db: Session = Depends(get_db),
) -> OverviewResponse:
    selected_location = _resolve_location(db, location)
    _ensure_hourly_data(db, selected_location)

    now = datetime.utcnow()
    next_24_hours = get_hours_between(db, selected_location.id, now, now + timedelta(hours=24))

    min_temp = min((h.temperature_c for h in next_24_hours if h.temperature_c is not None), default=None)
    max_temp = max((h.temperature_c for h in next_24_hours if h.temperature_c is not None), default=None)
    precipitation_total = round(sum((h.precipitation_mm or 0.0) for h in next_24_hours), 2)
    wind_values = [h.wind_speed_kph for h in next_24_hours if h.wind_speed_kph is not None]
    avg_wind = round(sum(wind_values) / len(wind_values), 2) if wind_values else None

    target_date = now.date()
    plan_rows = get_plan_windows(db, selected_location.id, target_date)
    outfit_row = get_or_generate_outfit(db, selected_location.id, target_date)
    health_row = get_or_generate_health_alert(db, selected_location.id, target_date)

    anomalies_count = count_recent_anomalies(db, selected_location.id, window_days=7)
    next_hour_prediction = predict_next_hour_temperature(db, selected_location.id)

    alert_level = "low"
    if health_row:
        highest = max(health_row.heat_risk, health_row.cold_risk, health_row.dehydration_risk, health_row.asthma_proxy_risk)
        if highest >= 70:
            alert_level = "high"
        elif highest >= 40:
            alert_level = "medium"

    recommendations = [row.summary for row in plan_rows[:2]]
    if outfit_row:
        recommendations.append(outfit_row.summary)
    if health_row:
        recommendations.append(health_row.summary)
    if next_hour_prediction is not None:
        recommendations.append(f"Model estimates next-hour temperature near {next_hour_prediction:.1f} C.")

    llm_hint = summarize_section(
        "overview",
        {
            "location": selected_location.name,
            "next_24h": {
                "min_temp_c": min_temp,
                "max_temp_c": max_temp,
                "precipitation_total_mm": precipitation_total,
                "avg_wind_kph": avg_wind,
            },
            "alert_level": alert_level,
            "anomalies_last_7d": anomalies_count,
            "next_hour_temperature_prediction_c": next_hour_prediction,
        },
    )
    recommendations.append(llm_hint)

    return OverviewResponse(
        location=_location_read(selected_location),
        generated_at=datetime.utcnow(),
        next_24h=OverviewStats(
            min_temp_c=min_temp,
            max_temp_c=max_temp,
            precipitation_total_mm=precipitation_total,
            avg_wind_kph=avg_wind,
        ),
        top_recommendations=recommendations,
        alert_level=alert_level,
        anomalies_last_7d=anomalies_count,
        next_hour_temperature_prediction_c=next_hour_prediction,
    )


@router.get("/plan", response_model=PlanResponse)
def get_plan(
    location: str = Query(default=settings.default_location_name),
    target_date: date = Query(default_factory=lambda: datetime.utcnow().date()),
    db: Session = Depends(get_db),
) -> PlanResponse:
    selected_location = _resolve_location(db, location)
    _ensure_hourly_data(db, selected_location)

    rows = get_plan_windows(db, selected_location.id, target_date)
    items = [
        PlanWindowItem(
            category=row.category,
            best_hour=row.best_hour,
            score=row.score,
            summary=row.summary,
        )
        for row in rows
    ]

    return PlanResponse(
        location=_location_read(selected_location),
        target_date=target_date,
        windows=items,
    )


@router.get("/outfit", response_model=OutfitResponse)
def get_outfit(
    location: str = Query(default=settings.default_location_name),
    target_date: date = Query(default_factory=lambda: datetime.utcnow().date()),
    db: Session = Depends(get_db),
) -> OutfitResponse:
    selected_location = _resolve_location(db, location)
    _ensure_hourly_data(db, selected_location)

    row = get_or_generate_outfit(db, selected_location.id, target_date)
    if row is None:
        return OutfitResponse(
            location=_location_read(selected_location),
            target_date=target_date,
            summary="No weather data available for this date yet.",
            umbrella=False,
            layer_level="medium",
            shoes="Breathable sneakers",
            sunscreen="Optional SPF 15",
            hydration_liters=2.0,
        )

    return OutfitResponse(
        location=_location_read(selected_location),
        target_date=target_date,
        summary=row.summary,
        umbrella=row.umbrella,
        layer_level=row.layer_level,
        shoes=row.shoes,
        sunscreen=row.sunscreen,
        hydration_liters=row.hydration_liters,
    )


@router.get("/health", response_model=HealthResponse)
def get_health(
    location: str = Query(default=settings.default_location_name),
    target_date: date = Query(default_factory=lambda: datetime.utcnow().date()),
    db: Session = Depends(get_db),
) -> HealthResponse:
    selected_location = _resolve_location(db, location)
    _ensure_hourly_data(db, selected_location)

    row = get_or_generate_health_alert(db, selected_location.id, target_date)
    if row is None:
        return HealthResponse(
            location=_location_read(selected_location),
            target_date=target_date,
            heat_risk=0,
            cold_risk=0,
            dehydration_risk=0,
            sleep_comfort_index=50,
            asthma_proxy_risk=0,
            summary="No weather data available for this date yet.",
        )

    return HealthResponse(
        location=_location_read(selected_location),
        target_date=target_date,
        heat_risk=row.heat_risk,
        cold_risk=row.cold_risk,
        dehydration_risk=row.dehydration_risk,
        sleep_comfort_index=row.sleep_comfort_index,
        asthma_proxy_risk=row.asthma_proxy_risk,
        summary=row.summary,
    )


@router.get("/anomalies", response_model=AnomaliesResponse)
def get_anomalies(
    location: str = Query(default=settings.default_location_name),
    window_days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
) -> AnomaliesResponse:
    selected_location = _resolve_location(db, location)
    _ensure_hourly_data(db, selected_location)

    detect_anomalies(db, selected_location.id)
    rows = list_anomalies(db, selected_location.id, window_days=window_days)

    items = [
        AnomalyItem(
            detected_at=row.detected_at,
            metric=row.metric,
            anomaly_type=row.anomaly_type,
            severity=row.severity,
            expected_value=row.expected_value,
            observed_value=row.observed_value,
            z_score=row.z_score,
            summary=row.summary,
        )
        for row in rows
    ]

    return AnomaliesResponse(
        location=_location_read(selected_location),
        window_days=window_days,
        items=items,
    )
