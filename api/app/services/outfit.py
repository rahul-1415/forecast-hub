from datetime import date

from sqlalchemy.orm import Session

from ..models import OutfitRecommendation
from .features import get_hours_for_date, safe_mean


def _layer_from_temp(avg_temp: float | None) -> str:
    if avg_temp is None:
        return "medium"
    if avg_temp <= 5:
        return "heavy"
    if avg_temp <= 16:
        return "medium"
    return "light"


def _sunscreen_from_uv(max_uv: float | None) -> str:
    if max_uv is None or max_uv < 3:
        return "Optional SPF 15"
    if max_uv < 6:
        return "SPF 30"
    if max_uv < 8:
        return "SPF 50"
    return "SPF 50+ (reapply)"


def _hydration_liters(avg_temp: float | None, max_uv: float | None) -> float:
    baseline = 2.0
    if avg_temp is not None and avg_temp > 25:
        baseline += 0.75
    if avg_temp is not None and avg_temp > 32:
        baseline += 0.5
    if max_uv is not None and max_uv > 6:
        baseline += 0.5
    return round(baseline, 2)


def _upsert_outfit(
    db: Session,
    *,
    location_id: int,
    target_date: date,
    summary: str,
    umbrella: bool,
    layer_level: str,
    shoes: str,
    sunscreen: str,
    hydration_liters: float,
) -> OutfitRecommendation:
    existing = (
        db.query(OutfitRecommendation)
        .filter(
            OutfitRecommendation.location_id == location_id,
            OutfitRecommendation.target_date == target_date,
        )
        .first()
    )

    if existing:
        existing.summary = summary
        existing.umbrella = umbrella
        existing.layer_level = layer_level
        existing.shoes = shoes
        existing.sunscreen = sunscreen
        existing.hydration_liters = hydration_liters
        return existing

    row = OutfitRecommendation(
        location_id=location_id,
        target_date=target_date,
        summary=summary,
        umbrella=umbrella,
        layer_level=layer_level,
        shoes=shoes,
        sunscreen=sunscreen,
        hydration_liters=hydration_liters,
    )
    db.add(row)
    return row


def get_or_generate_outfit(db: Session, location_id: int, target_date: date) -> OutfitRecommendation | None:
    existing = (
        db.query(OutfitRecommendation)
        .filter(
            OutfitRecommendation.location_id == location_id,
            OutfitRecommendation.target_date == target_date,
        )
        .first()
    )
    if existing:
        return existing

    hours = get_hours_for_date(db, location_id, target_date)
    if not hours:
        return None

    avg_temp = safe_mean([h.apparent_temperature_c or h.temperature_c for h in hours])
    max_precip = max((h.precipitation_mm or 0.0) for h in hours)
    max_rain = max((h.rain_mm or 0.0) for h in hours)
    max_uv = max((h.uv_index or 0.0) for h in hours)

    layer_level = _layer_from_temp(avg_temp)
    umbrella = (max_precip > 0.4) or (max_rain > 0.3)
    shoes = "Waterproof shoes" if umbrella else "Breathable sneakers"
    sunscreen = _sunscreen_from_uv(max_uv)
    hydration = _hydration_liters(avg_temp, max_uv)

    summary = (
        f"Wear {layer_level} layers, use {shoes.lower()}, "
        f"and plan for {hydration}L hydration. "
        f"{'Carry an umbrella.' if umbrella else 'Umbrella not required for most hours.'}"
    )

    row = _upsert_outfit(
        db,
        location_id=location_id,
        target_date=target_date,
        summary=summary,
        umbrella=umbrella,
        layer_level=layer_level,
        shoes=shoes,
        sunscreen=sunscreen,
        hydration_liters=hydration,
    )
    db.commit()
    db.refresh(row)
    return row
