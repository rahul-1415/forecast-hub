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


def get_or_create_location(
    db: Session,
    name: str,
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str | None = None,
) -> Location:
    location = get_location_by_name(db, name)
    if location:
        return location

    if latitude is None or longitude is None:
        # Fall back to default coordinates if a new location name is requested without coordinates.
        latitude = settings.default_location_latitude
        longitude = settings.default_location_longitude
    if timezone is None:
        timezone = settings.default_location_timezone

    location = Location(
        name=name,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        is_active=True,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location
