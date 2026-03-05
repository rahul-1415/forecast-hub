from datetime import date, datetime, time, timedelta

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models import HourlyWeather


def get_hours_for_date(db: Session, location_id: int, target_date: date) -> list[HourlyWeather]:
    start = datetime.combine(target_date, time.min)
    end = start + timedelta(days=1)
    return (
        db.query(HourlyWeather)
        .filter(
            and_(
                HourlyWeather.location_id == location_id,
                HourlyWeather.timestamp >= start,
                HourlyWeather.timestamp < end,
            )
        )
        .order_by(HourlyWeather.timestamp.asc())
        .all()
    )


def get_hours_between(db: Session, location_id: int, start: datetime, end: datetime) -> list[HourlyWeather]:
    return (
        db.query(HourlyWeather)
        .filter(
            and_(
                HourlyWeather.location_id == location_id,
                HourlyWeather.timestamp >= start,
                HourlyWeather.timestamp < end,
            )
        )
        .order_by(HourlyWeather.timestamp.asc())
        .all()
    )


def safe_mean(values: list[float | None]) -> float | None:
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
