from datetime import datetime, timedelta
from statistics import mean, pstdev

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models import AnomalyEvent, HourlyWeather


def _severity_from_z(z_score: float | None) -> str:
    if z_score is None:
        return "medium"
    if abs(z_score) >= 4:
        return "high"
    if abs(z_score) >= 3:
        return "medium"
    return "low"


def _insert_anomaly_if_missing(
    db: Session,
    *,
    location_id: int,
    detected_at: datetime,
    metric: str,
    anomaly_type: str,
    summary: str,
    observed_value: float | None,
    expected_value: float | None,
    z_score: float | None,
) -> AnomalyEvent | None:
    existing = (
        db.query(AnomalyEvent)
        .filter(
            AnomalyEvent.location_id == location_id,
            AnomalyEvent.detected_at == detected_at,
            AnomalyEvent.metric == metric,
            AnomalyEvent.anomaly_type == anomaly_type,
        )
        .first()
    )
    if existing:
        return None

    row = AnomalyEvent(
        location_id=location_id,
        detected_at=detected_at,
        metric=metric,
        anomaly_type=anomaly_type,
        severity=_severity_from_z(z_score),
        expected_value=expected_value,
        observed_value=observed_value,
        z_score=z_score,
        summary=summary,
        details=None,
    )
    db.add(row)
    return row


def detect_anomalies(db: Session, location_id: int, lookback_days: int = 14) -> list[AnomalyEvent]:
    now = datetime.utcnow()
    start = now - timedelta(days=lookback_days)

    rows = (
        db.query(HourlyWeather)
        .filter(
            and_(
                HourlyWeather.location_id == location_id,
                HourlyWeather.timestamp >= start,
                HourlyWeather.timestamp <= now + timedelta(days=2),
            )
        )
        .order_by(HourlyWeather.timestamp.asc())
        .all()
    )

    if len(rows) < 30:
        return []

    created: list[AnomalyEvent] = []

    temps = [r.temperature_c for r in rows if r.temperature_c is not None]
    precips = [r.precipitation_mm for r in rows if r.precipitation_mm is not None]

    temp_mean = mean(temps) if temps else 0.0
    temp_std = pstdev(temps) if len(temps) > 1 else 0.0

    precip_mean = mean(precips) if precips else 0.0
    precip_std = pstdev(precips) if len(precips) > 1 else 0.0

    for idx, row in enumerate(rows):
        if row.temperature_c is not None and temp_std > 0:
            temp_z = (row.temperature_c - temp_mean) / temp_std
            if abs(temp_z) >= 3:
                anomaly = _insert_anomaly_if_missing(
                    db,
                    location_id=location_id,
                    detected_at=row.timestamp,
                    metric="temperature_c",
                    anomaly_type="zscore_outlier",
                    summary=f"Temperature anomaly detected at {row.timestamp.isoformat()}.",
                    observed_value=row.temperature_c,
                    expected_value=temp_mean,
                    z_score=temp_z,
                )
                if anomaly:
                    created.append(anomaly)

        if row.precipitation_mm is not None and precip_std > 0:
            precip_z = (row.precipitation_mm - precip_mean) / precip_std
            if abs(precip_z) >= 3:
                anomaly = _insert_anomaly_if_missing(
                    db,
                    location_id=location_id,
                    detected_at=row.timestamp,
                    metric="precipitation_mm",
                    anomaly_type="zscore_outlier",
                    summary=f"Precipitation anomaly detected at {row.timestamp.isoformat()}.",
                    observed_value=row.precipitation_mm,
                    expected_value=precip_mean,
                    z_score=precip_z,
                )
                if anomaly:
                    created.append(anomaly)

        if idx == 0:
            continue
        prev = rows[idx - 1]

        if row.temperature_c is not None and prev.temperature_c is not None:
            delta_t = row.temperature_c - prev.temperature_c
            if abs(delta_t) >= 8:
                anomaly = _insert_anomaly_if_missing(
                    db,
                    location_id=location_id,
                    detected_at=row.timestamp,
                    metric="temperature_c",
                    anomaly_type="hourly_spike",
                    summary=(
                        f"Sharp temperature {'increase' if delta_t > 0 else 'drop'} "
                        f"of {delta_t:.1f}C in one hour."
                    ),
                    observed_value=row.temperature_c,
                    expected_value=prev.temperature_c,
                    z_score=None,
                )
                if anomaly:
                    created.append(anomaly)

        if row.precipitation_mm is not None and prev.precipitation_mm is not None:
            delta_p = row.precipitation_mm - prev.precipitation_mm
            if delta_p >= 5:
                anomaly = _insert_anomaly_if_missing(
                    db,
                    location_id=location_id,
                    detected_at=row.timestamp,
                    metric="precipitation_mm",
                    anomaly_type="sudden_precipitation",
                    summary=f"Sudden precipitation spike of {delta_p:.1f} mm/h.",
                    observed_value=row.precipitation_mm,
                    expected_value=prev.precipitation_mm,
                    z_score=None,
                )
                if anomaly:
                    created.append(anomaly)

    db.commit()
    for row in created:
        db.refresh(row)
    return created


def list_anomalies(db: Session, location_id: int, window_days: int = 7) -> list[AnomalyEvent]:
    start = datetime.utcnow() - timedelta(days=window_days)
    return (
        db.query(AnomalyEvent)
        .filter(
            AnomalyEvent.location_id == location_id,
            AnomalyEvent.detected_at >= start,
        )
        .order_by(AnomalyEvent.detected_at.desc())
        .all()
    )
