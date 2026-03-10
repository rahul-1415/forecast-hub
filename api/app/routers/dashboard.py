from datetime import date, datetime, timedelta
import threading

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AnomalyEvent, Location
from ..schemas import (
    AnomaliesResponse,
    AnomalyItem,
    HealthResponse,
    HourlyTemperatureBandPoint,
    HourlyTemperaturePoint,
    LocationSuggestion,
    LocationRead,
    OutfitResponse,
    OverviewResponse,
    OverviewStats,
    PlanResponse,
    PlanWindowItem,
    RecommendationDetail,
    SourceComparison,
    WeeklySummary,
)
from ..services.anomalies import detect_anomalies, list_anomalies
from ..services.features import get_hours_between, get_latest_hours
from ..services.health import get_or_generate_health_alert
from ..services.ingestion import ingest_hourly_forecast
from ..services.llm import summarize_section
from ..services.location import get_or_create_location, search_location_suggestions
from ..services.model_workflow import (
    get_inference_model_rmse,
    predict_hourly_temperature_series,
    predict_next_hour_temperature,
)
from ..services.orchestration import count_recent_anomalies
from ..services.outfit import get_or_generate_outfit
from ..services.plan import get_plan_windows

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])

_overview_cache_lock = threading.Lock()
_overview_cache: dict[str, tuple[datetime, OverviewResponse]] = {}
_OVERVIEW_CACHE_TTL_SECONDS = 90
_OVERVIEW_CACHE_STALE_SECONDS = 60 * 60


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
    try:
        ingest_hourly_forecast(db, location)
    except Exception:
        # Fail open to allow stale fallback responses from historical data.
        return


def _build_source_comparison(
    *,
    open_meteo_next_hour: float | None,
    custom_model_next_hour: float | None,
    rmse_c: float | None,
) -> SourceComparison:
    delta_c = None
    if open_meteo_next_hour is not None and custom_model_next_hour is not None:
        delta_c = custom_model_next_hour - open_meteo_next_hour

    if custom_model_next_hour is None:
        return SourceComparison(
            open_meteo_next_hour_c=open_meteo_next_hour,
            custom_ml_next_hour_c=custom_model_next_hour,
            delta_c=delta_c,
            rmse_c=rmse_c,
            preferred_source="open_meteo",
            confidence_note="Custom model unavailable right now; using Open-Meteo as primary source.",
        )

    if rmse_c is not None and rmse_c <= 2.0:
        note = f"Custom ML recent RMSE is {rmse_c:.2f} C, so model output is preferred."
        source = "custom_ml"
    elif rmse_c is not None and rmse_c >= 4.0:
        note = f"Custom ML RMSE is {rmse_c:.2f} C; Open-Meteo is currently more conservative."
        source = "open_meteo"
    else:
        note = "Both sources are shown; differences are within a moderate confidence range."
        source = "mixed"

    return SourceComparison(
        open_meteo_next_hour_c=open_meteo_next_hour,
        custom_ml_next_hour_c=custom_model_next_hour,
        delta_c=delta_c,
        rmse_c=rmse_c,
        preferred_source=source,
        confidence_note=note,
    )


def _build_weekly_summary(
    db: Session,
    *,
    location_id: int,
    target_date: date,
) -> WeeklySummary:
    end_current = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
    start_current = end_current - timedelta(days=7)
    start_previous = start_current - timedelta(days=7)
    end_previous = start_current

    current_rows = get_hours_between(db, location_id, start_current, end_current)
    previous_rows = get_hours_between(db, location_id, start_previous, end_previous)

    current_temps = [row.temperature_c for row in current_rows if row.temperature_c is not None]
    previous_temps = [row.temperature_c for row in previous_rows if row.temperature_c is not None]
    current_avg_temp = (sum(current_temps) / len(current_temps)) if current_temps else None
    previous_avg_temp = (sum(previous_temps) / len(previous_temps)) if previous_temps else None
    avg_temp_delta = (
        (current_avg_temp - previous_avg_temp)
        if current_avg_temp is not None and previous_avg_temp is not None
        else None
    )

    current_precip = sum((row.precipitation_mm or 0.0) for row in current_rows)
    previous_precip = sum((row.precipitation_mm or 0.0) for row in previous_rows)
    precip_delta = current_precip - previous_precip if previous_rows else None

    anomalies_current = (
        db.query(AnomalyEvent)
        .filter(
            and_(
                AnomalyEvent.location_id == location_id,
                AnomalyEvent.detected_at >= start_current,
                AnomalyEvent.detected_at < end_current,
            )
        )
        .count()
    )
    anomalies_previous = (
        db.query(AnomalyEvent)
        .filter(
            and_(
                AnomalyEvent.location_id == location_id,
                AnomalyEvent.detected_at >= start_previous,
                AnomalyEvent.detected_at < end_previous,
            )
        )
        .count()
    )

    plan_rows = get_plan_windows(db, location_id, target_date)
    best_windows = [
        f"{row.category}: {row.best_hour:02d}:00 ({row.score:.0f}/100)"
        for row in sorted(plan_rows, key=lambda row: row.score, reverse=True)[:3]
    ]

    insights: list[str] = []
    if avg_temp_delta is not None:
        direction = "warmer" if avg_temp_delta >= 0 else "cooler"
        insights.append(f"This week is {abs(avg_temp_delta):.1f} C {direction} than the previous week.")
    if precip_delta is not None:
        direction = "more rain" if precip_delta >= 0 else "less rain"
        insights.append(f"Precipitation trend shows {abs(precip_delta):.1f} mm {direction} week-over-week.")
    anomaly_delta = anomalies_current - anomalies_previous
    if anomaly_delta > 0:
        insights.append(f"Anomaly count increased by {anomaly_delta} over the previous week.")
    elif anomaly_delta < 0:
        insights.append(f"Anomaly count decreased by {abs(anomaly_delta)} versus the previous week.")
    else:
        insights.append("Anomaly count is stable week-over-week.")

    return WeeklySummary(
        window_start=start_current.date(),
        window_end=(end_current - timedelta(days=1)).date(),
        average_temp_c=round(current_avg_temp, 2) if current_avg_temp is not None else None,
        average_temp_delta_vs_prev_week_c=round(avg_temp_delta, 2) if avg_temp_delta is not None else None,
        total_precipitation_mm=round(current_precip, 2),
        precipitation_delta_vs_prev_week_mm=round(precip_delta, 2) if precip_delta is not None else None,
        anomalies_last_7d=anomalies_current,
        anomalies_delta_vs_prev_week=anomaly_delta,
        best_windows=best_windows,
        insights=insights,
    )


def _build_recommendation_details(
    *,
    plan_rows,
    outfit_row,
    health_row,
    next_hour_prediction: float | None,
    open_meteo_next_hour_temperature: float | None,
    precipitation_total: float,
    avg_wind: float | None,
) -> list[RecommendationDetail]:
    details: list[RecommendationDetail] = []
    for row in plan_rows[:2]:
        details.append(
            RecommendationDetail(
                recommendation=row.summary,
                why=f"{row.category.title()} scored {row.score:.0f}/100 at {row.best_hour:02d}:00 based on temperature, precipitation, wind, and comfort weights.",
                source="plan",
            )
        )

    if outfit_row is not None:
        details.append(
            RecommendationDetail(
                recommendation=outfit_row.summary,
                why="Layer, umbrella, and hydration guidance are derived from daily apparent temperature, rainfall chance, and UV intensity.",
                source="outfit",
            )
        )

    if health_row is not None:
        details.append(
            RecommendationDetail(
                recommendation=health_row.summary,
                why="Health risk scores combine temperature extremes, humidity, UV load, pressure swing, and rainfall patterns.",
                source="health",
            )
        )

    if next_hour_prediction is not None:
        if open_meteo_next_hour_temperature is not None:
            delta = next_hour_prediction - open_meteo_next_hour_temperature
            model_note = f"Custom ML differs from Open-Meteo by {delta:+.1f} C next hour."
        else:
            model_note = "Custom ML next-hour estimate is available and used in recommendations."
        details.append(
            RecommendationDetail(
                recommendation=f"Model estimates next-hour temperature near {next_hour_prediction:.1f} C.",
                why=model_note,
                source="custom_ml",
            )
        )

    details.append(
        RecommendationDetail(
            recommendation="Watch for changing conditions in the next 24h.",
            why=f"Expected precipitation is {precipitation_total:.1f} mm and average wind is {avg_wind:.1f} kph." if avg_wind is not None else f"Expected precipitation is {precipitation_total:.1f} mm.",
            source="rule_engine",
        )
    )

    return details


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    location: str = Query(default=settings.default_location_name),
    db: Session = Depends(get_db),
) -> OverviewResponse:
    cache_key = location.strip().lower()
    now = datetime.utcnow()
    with _overview_cache_lock:
        cached = _overview_cache.get(cache_key)
    if cached:
        cached_at, cached_response = cached
        age = (now - cached_at).total_seconds()
        if age <= _OVERVIEW_CACHE_TTL_SECONDS:
            return cached_response.model_copy(
                update={"generated_at": datetime.utcnow(), "data_freshness": "fresh_cache", "stale_reason": None}
            )

    try:
        selected_location = _resolve_location(db, location)
        _ensure_hourly_data(db, selected_location)

        next_24_hours = get_hours_between(db, selected_location.id, now, now + timedelta(hours=24))
        data_freshness = "fresh"
        stale_reason = None
        if not next_24_hours:
            next_24_hours = get_latest_hours(db, selected_location.id, limit=24)
            if next_24_hours:
                data_freshness = "stale_data"
                stale_reason = "Using most recent stored weather rows due to upstream forecast fetch issues."

        current_temperature = next_24_hours[0].temperature_c if next_24_hours else None
        open_meteo_next_hour_temperature = next_24_hours[1].temperature_c if len(next_24_hours) > 1 else current_temperature

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
        model_rmse = get_inference_model_rmse(db)

        alert_level = "low"
        if health_row:
            highest = max(
                health_row.heat_risk,
                health_row.cold_risk,
                health_row.dehydration_risk,
                health_row.asthma_proxy_risk,
            )
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

        try:
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
        except Exception:
            recommendations.append("Recommendations are generated from live weather trends and current risk levels.")

        hourly_points = [
            HourlyTemperaturePoint(timestamp=hour.timestamp, temperature_c=hour.temperature_c)
            for hour in next_24_hours
        ]
        hourly_custom_predictions = predict_hourly_temperature_series(db, next_24_hours)
        hourly_custom_points = [
            HourlyTemperaturePoint(timestamp=hour.timestamp, temperature_c=prediction)
            for hour, prediction in zip(next_24_hours, hourly_custom_predictions)
        ]

        confidence_width = model_rmse if model_rmse is not None else 2.5
        hourly_custom_bands = [
            HourlyTemperatureBandPoint(
                timestamp=hour.timestamp,
                temperature_c=prediction,
                lower_c=(prediction - confidence_width) if prediction is not None else None,
                upper_c=(prediction + confidence_width) if prediction is not None else None,
            )
            for hour, prediction in zip(next_24_hours, hourly_custom_predictions)
        ]
        source_comparison = _build_source_comparison(
            open_meteo_next_hour=open_meteo_next_hour_temperature,
            custom_model_next_hour=next_hour_prediction,
            rmse_c=model_rmse,
        )
        recommendation_details = _build_recommendation_details(
            plan_rows=plan_rows,
            outfit_row=outfit_row,
            health_row=health_row,
            next_hour_prediction=next_hour_prediction,
            open_meteo_next_hour_temperature=open_meteo_next_hour_temperature,
            precipitation_total=precipitation_total,
            avg_wind=avg_wind,
        )
        weekly_summary = _build_weekly_summary(
            db,
            location_id=selected_location.id,
            target_date=target_date,
        )

        response = OverviewResponse(
            location=_location_read(selected_location),
            generated_at=datetime.utcnow(),
            current_temperature_c=current_temperature,
            next_hour_temperature_open_meteo_c=open_meteo_next_hour_temperature,
            next_hour_temperature_custom_model_c=next_hour_prediction,
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
            hourly_temperatures_24h=hourly_points,
            hourly_temperatures_24h_custom_model=hourly_custom_points,
            hourly_temperatures_24h_custom_model_bands=hourly_custom_bands,
            custom_model_rmse_c=model_rmse,
            source_comparison_next_hour=source_comparison,
            recommendation_details=recommendation_details,
            weekly_summary=weekly_summary,
            data_freshness=data_freshness,
            stale_reason=stale_reason,
        )
        with _overview_cache_lock:
            _overview_cache[cache_key] = (datetime.utcnow(), response)
        return response
    except Exception as exc:
        with _overview_cache_lock:
            cached = _overview_cache.get(cache_key)
        if cached:
            cached_at, cached_response = cached
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age <= _OVERVIEW_CACHE_STALE_SECONDS:
                return cached_response.model_copy(
                    update={
                        "generated_at": datetime.utcnow(),
                        "data_freshness": "stale_cache",
                        "stale_reason": f"Serving cached overview due to upstream error: {exc}",
                    }
                )
        raise


@router.get("/weekly-summary", response_model=WeeklySummary)
def get_weekly_summary(
    location: str = Query(default=settings.default_location_name),
    db: Session = Depends(get_db),
) -> WeeklySummary:
    selected_location = _resolve_location(db, location)
    _ensure_hourly_data(db, selected_location)
    return _build_weekly_summary(
        db,
        location_id=selected_location.id,
        target_date=datetime.utcnow().date(),
    )


@router.get("/location-suggestions", response_model=list[LocationSuggestion])
def get_location_suggestions(
    query: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=6, ge=1, le=12),
) -> list[LocationSuggestion]:
    return [
        LocationSuggestion(name=item["name"], label=item["label"])
        for item in search_location_suggestions(query, limit=limit)
    ]


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
