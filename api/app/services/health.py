from datetime import date

from sqlalchemy.orm import Session

from ..models import HealthAlert
from .features import clamp, get_hours_for_date, safe_mean


def _risk_score(value: float, low: float, high: float) -> int:
    if value <= low:
        return 0
    if value >= high:
        return 100
    return int(((value - low) / (high - low)) * 100)


def _upsert_health(
    db: Session,
    *,
    location_id: int,
    target_date: date,
    heat_risk: int,
    cold_risk: int,
    dehydration_risk: int,
    sleep_comfort_index: int,
    asthma_proxy_risk: int,
    summary: str,
) -> HealthAlert:
    existing = (
        db.query(HealthAlert)
        .filter(
            HealthAlert.location_id == location_id,
            HealthAlert.target_date == target_date,
        )
        .first()
    )

    if existing:
        existing.heat_risk = heat_risk
        existing.cold_risk = cold_risk
        existing.dehydration_risk = dehydration_risk
        existing.sleep_comfort_index = sleep_comfort_index
        existing.asthma_proxy_risk = asthma_proxy_risk
        existing.summary = summary
        return existing

    row = HealthAlert(
        location_id=location_id,
        target_date=target_date,
        heat_risk=heat_risk,
        cold_risk=cold_risk,
        dehydration_risk=dehydration_risk,
        sleep_comfort_index=sleep_comfort_index,
        asthma_proxy_risk=asthma_proxy_risk,
        summary=summary,
    )
    db.add(row)
    return row


def get_or_generate_health_alert(db: Session, location_id: int, target_date: date) -> HealthAlert | None:
    existing = (
        db.query(HealthAlert)
        .filter(
            HealthAlert.location_id == location_id,
            HealthAlert.target_date == target_date,
        )
        .first()
    )
    if existing:
        return existing

    hours = get_hours_for_date(db, location_id, target_date)
    if not hours:
        return None

    apparent_values = [h.apparent_temperature_c or h.temperature_c for h in hours if (h.apparent_temperature_c or h.temperature_c) is not None]
    humidity_values = [h.relative_humidity for h in hours if h.relative_humidity is not None]
    uv_values = [h.uv_index for h in hours if h.uv_index is not None]

    max_apparent = max(apparent_values) if apparent_values else 0.0
    min_apparent = min(apparent_values) if apparent_values else 0.0
    avg_humidity = safe_mean(humidity_values) or 50.0
    max_uv = max(uv_values) if uv_values else 0.0

    heat_risk = _risk_score(max_apparent, 24, 40)
    cold_risk = _risk_score(abs(min_apparent), 2, 18) if min_apparent < 2 else 0

    dehydration_raw = (heat_risk * 0.5) + (_risk_score(max_uv, 3, 10) * 0.3) + (_risk_score(100 - avg_humidity, 25, 70) * 0.2)
    dehydration_risk = int(clamp(dehydration_raw, 0, 100))

    night_hours = [
        h for h in hours if h.timestamp.hour >= 22 or h.timestamp.hour <= 6
    ]
    night_temp = safe_mean([h.apparent_temperature_c or h.temperature_c for h in night_hours])
    night_humidity = safe_mean([h.relative_humidity for h in night_hours])

    sleep_penalty = 0
    if night_temp is not None:
        if night_temp > 24:
            sleep_penalty += int((night_temp - 24) * 8)
        if night_temp < 12:
            sleep_penalty += int((12 - night_temp) * 5)
    if night_humidity is not None and night_humidity > 75:
        sleep_penalty += int((night_humidity - 75) * 1.2)
    sleep_comfort_index = int(clamp(100 - sleep_penalty, 0, 100))

    pressure_values = [h.pressure_hpa for h in hours if h.pressure_hpa is not None]
    pressure_swing = (max(pressure_values) - min(pressure_values)) if pressure_values else 0.0
    precip_total = sum((h.precipitation_mm or 0.0) for h in hours)
    asthma_proxy_risk = int(
        clamp(
            (_risk_score(avg_humidity, 65, 95) * 0.5)
            + (_risk_score(pressure_swing, 3, 15) * 0.3)
            + (_risk_score(precip_total, 2, 18) * 0.2),
            0,
            100,
        )
    )

    summary = (
        f"Heat risk {heat_risk}/100, cold risk {cold_risk}/100, dehydration risk {dehydration_risk}/100. "
        f"Sleep comfort {sleep_comfort_index}/100 and asthma proxy risk {asthma_proxy_risk}/100."
    )

    row = _upsert_health(
        db,
        location_id=location_id,
        target_date=target_date,
        heat_risk=heat_risk,
        cold_risk=cold_risk,
        dehydration_risk=dehydration_risk,
        sleep_comfort_index=sleep_comfort_index,
        asthma_proxy_risk=asthma_proxy_risk,
        summary=summary,
    )
    db.commit()
    db.refresh(row)
    return row
