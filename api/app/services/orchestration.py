from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import AnomalyEvent, JobRun, Location
from .anomalies import detect_anomalies
from .health import get_or_generate_health_alert
from .ingestion import ingest_hourly_forecast
from .location import ensure_default_location
from .notifications import run_notification_cycle
from .outfit import get_or_generate_outfit
from .plan import generate_plan_windows


def run_hourly_pipeline(db: Session) -> dict:
    ensure_default_location(db)

    run = JobRun(job_name="hourly_pipeline", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    active_locations = db.query(Location).filter(Location.is_active.is_(True)).all()

    total_ingested = 0
    total_plan_rows = 0
    total_anomalies = 0
    failed_locations: list[str] = []

    try:
        for location in active_locations:
            try:
                total_ingested += ingest_hourly_forecast(db, location)

                today = datetime.utcnow().date()
                tomorrow = today + timedelta(days=1)

                total_plan_rows += len(generate_plan_windows(db, location.id, today))
                total_plan_rows += len(generate_plan_windows(db, location.id, tomorrow))

                get_or_generate_outfit(db, location.id, today)
                get_or_generate_outfit(db, location.id, tomorrow)

                get_or_generate_health_alert(db, location.id, today)
                get_or_generate_health_alert(db, location.id, tomorrow)

                anomalies = detect_anomalies(db, location.id)
                total_anomalies += len(anomalies)
            except Exception as location_exc:
                failed_locations.append(f"{location.name}: {location_exc}")
                continue

        status = "success" if not failed_locations else "partial_success"
        message = "Pipeline completed successfully"
        if failed_locations:
            message = f"Pipeline completed with {len(failed_locations)} location failure(s): {'; '.join(failed_locations[:3])}"

        try:
            run_notification_cycle(db)
        except Exception:
            # Notification processing should not fail the weather pipeline.
            pass

        run.status = status
        run.finished_at = datetime.utcnow()
        run.message = message
        db.commit()

        return {
            "status": status,
            "processed_locations": len(active_locations),
            "ingested_rows": total_ingested,
            "generated_plan_rows": total_plan_rows,
            "generated_anomalies": total_anomalies,
            "message": message,
        }
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.message = str(exc)
        db.commit()
        raise


def count_recent_anomalies(db: Session, location_id: int, window_days: int = 7) -> int:
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    return (
        db.query(AnomalyEvent)
        .filter(AnomalyEvent.location_id == location_id, AnomalyEvent.detected_at >= cutoff)
        .count()
    )
