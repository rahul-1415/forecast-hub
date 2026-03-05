from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import HourlyWeather, Location


HOURLY_FIELDS = {
    "temperature_2m": "temperature_c",
    "apparent_temperature": "apparent_temperature_c",
    "precipitation": "precipitation_mm",
    "rain": "rain_mm",
    "relative_humidity_2m": "relative_humidity",
    "wind_speed_10m": "wind_speed_kph",
    "uv_index": "uv_index",
    "pressure_msl": "pressure_hpa",
    "cloud_cover": "cloud_cover",
    "is_day": "is_day",
}


def _parse_timestamp(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def fetch_hourly_forecast(location: Location) -> dict:
    params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": location.timezone,
        "forecast_days": 7,
        "hourly": ",".join(HOURLY_FIELDS.keys()),
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.get(settings.open_meteo_base_url, params=params)
        response.raise_for_status()
        return response.json()


def ingest_hourly_forecast(db: Session, location: Location) -> int:
    payload = fetch_hourly_forecast(location)
    hourly = payload.get("hourly", {})

    timestamps = hourly.get("time", [])
    inserted_or_updated = 0

    for index, ts in enumerate(timestamps):
        point = {
            db_field: (hourly.get(api_field) or [None])[index]
            for api_field, db_field in HOURLY_FIELDS.items()
        }
        point["timestamp"] = _parse_timestamp(ts)

        existing = (
            db.query(HourlyWeather)
            .filter(
                HourlyWeather.location_id == location.id,
                HourlyWeather.timestamp == point["timestamp"],
            )
            .first()
        )

        if existing:
            for key, value in point.items():
                setattr(existing, key, value)
        else:
            row = HourlyWeather(location_id=location.id, **point)
            db.add(row)

        inserted_or_updated += 1

    db.commit()
    return inserted_or_updated
