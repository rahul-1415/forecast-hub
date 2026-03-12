from datetime import date

from sqlalchemy.orm import Session

from ..models import HourlyWeather, PlanWindow
from .features import clamp, get_hours_for_date


CATEGORY_WEIGHTS = {
    "commute": {"temp": 0.25, "precip": 0.35, "wind": 0.25, "visibility": 0.15},
    "exercise": {"temp": 0.35, "precip": 0.3, "wind": 0.1, "humidity": 0.25},
    "errands": {"temp": 0.2, "precip": 0.45, "wind": 0.15, "humidity": 0.2},
}


def score_tier(score: float | None) -> str:
    if score is None:
        return "balanced"
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "strong"
    if score >= 55:
        return "moderate"
    if score >= 40:
        return "limited"
    return "challenging"


def build_plan_window_summary(category: str, best_hour: int, score: float | None) -> str:
    tier = score_tier(score)
    return f"Best {category} window is around {best_hour:02d}:00 with {tier} outdoor comfort."


def build_plan_window_why(category: str, best_hour: int, score: float | None) -> str:
    tier = score_tier(score)
    return (
        f"{category.title()} conditions near {best_hour:02d}:00 are {tier}, based on temperature, "
        "precipitation, wind, and comfort weighting."
    )


def _temperature_score(temp: float | None, low: float, high: float) -> float:
    if temp is None:
        return 0.5
    if low <= temp <= high:
        return 1.0
    if temp < low:
        return clamp(1.0 - (low - temp) / 20.0, 0.0, 1.0)
    return clamp(1.0 - (temp - high) / 20.0, 0.0, 1.0)


def _precip_score(precip: float | None) -> float:
    if precip is None:
        return 0.8
    return clamp(1.0 - precip / 6.0, 0.0, 1.0)


def _wind_score(wind: float | None) -> float:
    if wind is None:
        return 0.8
    return clamp(1.0 - wind / 40.0, 0.0, 1.0)


def _humidity_score(humidity: float | None) -> float:
    if humidity is None:
        return 0.8
    # 45-65% is neutral for outdoor comfort.
    if 45 <= humidity <= 65:
        return 1.0
    if humidity < 45:
        return clamp(1.0 - (45 - humidity) / 45.0, 0.0, 1.0)
    return clamp(1.0 - (humidity - 65) / 45.0, 0.0, 1.0)


def _visibility_score(cloud_cover: float | None) -> float:
    if cloud_cover is None:
        return 0.8
    return clamp(1.0 - cloud_cover / 120.0, 0.0, 1.0)


def _score_hour(hour: HourlyWeather, category: str) -> float:
    weights = CATEGORY_WEIGHTS[category]

    temp_range = {
        "commute": (6.0, 28.0),
        "exercise": (9.0, 24.0),
        "errands": (4.0, 30.0),
    }[category]

    temp_component = _temperature_score(hour.apparent_temperature_c or hour.temperature_c, *temp_range)
    precip_component = _precip_score(hour.precipitation_mm)
    wind_component = _wind_score(hour.wind_speed_kph)
    humidity_component = _humidity_score(hour.relative_humidity)
    visibility_component = _visibility_score(hour.cloud_cover)

    return round(
        (
            weights["temp"] * temp_component
            + weights["precip"] * precip_component
            + weights["wind"] * wind_component
            + weights.get("humidity", 0.0) * humidity_component
            + weights.get("visibility", 0.0) * visibility_component
        )
        * 100,
        2,
    )


def _upsert_plan_window(
    db: Session,
    *,
    location_id: int,
    target_date: date,
    category: str,
    best_hour: int,
    score: float,
    summary: str,
) -> PlanWindow:
    existing = (
        db.query(PlanWindow)
        .filter(
            PlanWindow.location_id == location_id,
            PlanWindow.target_date == target_date,
            PlanWindow.category == category,
        )
        .first()
    )

    if existing:
        existing.best_hour = best_hour
        existing.score = score
        existing.summary = summary
        return existing

    row = PlanWindow(
        location_id=location_id,
        target_date=target_date,
        category=category,
        best_hour=best_hour,
        score=score,
        summary=summary,
        details=None,
    )
    db.add(row)
    return row


def generate_plan_windows(db: Session, location_id: int, target_date: date) -> list[PlanWindow]:
    hours = get_hours_for_date(db, location_id, target_date)
    candidate_hours = [h for h in hours if 6 <= h.timestamp.hour <= 21]

    if not candidate_hours:
        return []

    rows: list[PlanWindow] = []
    for category in CATEGORY_WEIGHTS:
        scored = sorted(
            ((hour, _score_hour(hour, category)) for hour in candidate_hours),
            key=lambda item: item[1],
            reverse=True,
        )
        best_hour, best_score = scored[0]
        summary = build_plan_window_summary(category, best_hour.timestamp.hour, best_score)
        row = _upsert_plan_window(
            db,
            location_id=location_id,
            target_date=target_date,
            category=category,
            best_hour=best_hour.timestamp.hour,
            score=best_score,
            summary=summary,
        )
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def get_plan_windows(db: Session, location_id: int, target_date: date) -> list[PlanWindow]:
    rows = (
        db.query(PlanWindow)
        .filter(
            PlanWindow.location_id == location_id,
            PlanWindow.target_date == target_date,
        )
        .order_by(PlanWindow.category.asc())
        .all()
    )
    if rows:
        return rows
    return generate_plan_windows(db, location_id, target_date)
