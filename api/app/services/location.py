import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Location


def get_location_by_name(db: Session, name: str) -> Location | None:
    return db.query(Location).filter(Location.name == name).first()


def ensure_default_location(db: Session) -> Location:
    existing = get_location_by_name(db, settings.default_location_name)
    if existing:
        return existing

    location = Location(
        name=settings.default_location_name,
        latitude=settings.default_location_latitude,
        longitude=settings.default_location_longitude,
        timezone=settings.default_location_timezone,
        is_active=True,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def _is_default_coordinates(latitude: float, longitude: float, timezone: str) -> bool:
    return (
        abs(latitude - settings.default_location_latitude) < 1e-6
        and abs(longitude - settings.default_location_longitude) < 1e-6
        and timezone == settings.default_location_timezone
    )


def _geocode_search(name: str, count: int) -> list[dict]:
    params = {"name": name, "count": count, "language": "en", "format": "json"}
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(settings.open_meteo_geocoding_url, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    results = payload.get("results") or []
    return [result for result in results if isinstance(result, dict)]


def _geocode_location(name: str) -> tuple[float, float, str] | None:
    results = _geocode_search(name, count=1)
    if not results:
        return None

    item = results[0]
    latitude = item.get("latitude")
    longitude = item.get("longitude")
    timezone = item.get("timezone") or settings.default_location_timezone

    if latitude is None or longitude is None:
        return None

    return float(latitude), float(longitude), str(timezone)


def search_location_suggestions(query: str, limit: int = 6) -> list[dict[str, str]]:
    normalized = query.strip()
    if len(normalized) < 2:
        return []

    results = _geocode_search(normalized, count=limit)
    if not results:
        return []

    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in results:
        name = str(item.get("name") or "").strip()
        if not name:
            continue

        admin1 = str(item.get("admin1") or "").strip()
        country = str(item.get("country") or "").strip()
        parts = [name]
        if admin1 and admin1.lower() != name.lower():
            parts.append(admin1)
        if country:
            parts.append(country)
        label = ", ".join(parts)

        key = f"{name.lower()}|{label.lower()}"
        if key in seen:
            continue
        seen.add(key)

        suggestions.append({"name": name, "label": label})

    return suggestions


def get_or_create_location(
    db: Session,
    name: str,
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str | None = None,
) -> Location:
    normalized_name = name.strip()
    location = get_location_by_name(db, normalized_name)
    if location:
        # Upgrade previously created placeholder rows that used default coordinates.
        if (
            normalized_name.lower() != settings.default_location_name.lower()
            and _is_default_coordinates(location.latitude, location.longitude, location.timezone)
        ):
            geocoded = _geocode_location(normalized_name)
            if geocoded:
                geo_latitude, geo_longitude, geo_timezone = geocoded
                location.latitude = geo_latitude
                location.longitude = geo_longitude
                location.timezone = geo_timezone
                db.commit()
                db.refresh(location)
        return location

    if latitude is None or longitude is None:
        geocoded = _geocode_location(normalized_name)
        if geocoded:
            latitude, longitude, geocoded_timezone = geocoded
            timezone = timezone or geocoded_timezone
        else:
            # Fall back to default coordinates if geocoding fails.
            latitude = settings.default_location_latitude
            longitude = settings.default_location_longitude
    if timezone is None:
        timezone = settings.default_location_timezone

    location = Location(
        name=normalized_name,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        is_active=True,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location
