from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import (
    NotificationDeliveryLogItem,
    NotificationDeliveryLogsResponse,
    NotificationSendTestRequest,
    NotificationSendTestResponse,
    NotificationSubscriptionCreate,
    NotificationSubscriptionItem,
    NotificationSubscriptionUpdate,
    NotificationSubscriptionsResponse,
)
from ..services.notifications import (
    create_or_update_subscription,
    delete_subscription,
    enqueue_test_notification,
    list_delivery_logs,
    list_subscriptions,
    run_notification_cycle,
    update_subscription,
)


router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


def _to_subscription_item(row) -> NotificationSubscriptionItem:
    return NotificationSubscriptionItem(
        id=row.id,
        location_name=row.location_name,
        channel=row.channel,
        destination=row.destination,
        enabled=row.enabled,
        schedule_time=row.schedule_time,
        timezone=row.timezone,
        include_outfit=row.include_outfit,
        include_health=row.include_health,
        include_plan=row.include_plan,
        quiet_hours_enabled=row.quiet_hours_enabled,
        quiet_start=row.quiet_start,
        quiet_end=row.quiet_end,
        escalation_enabled=row.escalation_enabled,
        next_run_at=row.next_run_at,
        last_sent_at=row.last_sent_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/subscriptions", response_model=NotificationSubscriptionsResponse)
def get_subscriptions(db: Session = Depends(get_db)) -> NotificationSubscriptionsResponse:
    rows = list_subscriptions(db)
    return NotificationSubscriptionsResponse(items=[_to_subscription_item(row) for row in rows])


@router.post("/subscriptions", response_model=NotificationSubscriptionItem)
def upsert_subscription(payload: NotificationSubscriptionCreate, db: Session = Depends(get_db)) -> NotificationSubscriptionItem:
    row = create_or_update_subscription(
        db,
        location_name=payload.location_name,
        channel=payload.channel,
        destination=payload.destination,
        enabled=payload.enabled,
        schedule_time=payload.schedule_time,
        timezone_name=payload.timezone,
        include_outfit=payload.include_outfit,
        include_health=payload.include_health,
        include_plan=payload.include_plan,
        quiet_hours_enabled=payload.quiet_hours_enabled,
        quiet_start=payload.quiet_start,
        quiet_end=payload.quiet_end,
        escalation_enabled=payload.escalation_enabled,
    )
    return _to_subscription_item(row)


@router.patch("/subscriptions/{subscription_id}", response_model=NotificationSubscriptionItem)
def patch_subscription(
    subscription_id: int,
    payload: NotificationSubscriptionUpdate,
    db: Session = Depends(get_db),
) -> NotificationSubscriptionItem:
    row = update_subscription(
        db,
        subscription_id,
        location_name=payload.location_name,
        enabled=payload.enabled,
        schedule_time=payload.schedule_time,
        timezone=payload.timezone,
        include_outfit=payload.include_outfit,
        include_health=payload.include_health,
        include_plan=payload.include_plan,
        quiet_hours_enabled=payload.quiet_hours_enabled,
        quiet_start=payload.quiet_start,
        quiet_end=payload.quiet_end,
        escalation_enabled=payload.escalation_enabled,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return _to_subscription_item(row)


@router.delete("/subscriptions/{subscription_id}")
def remove_subscription(subscription_id: int, db: Session = Depends(get_db)) -> dict:
    deleted = delete_subscription(db, subscription_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return {"status": "ok"}


@router.post("/send-test", response_model=NotificationSendTestResponse)
def send_test(payload: NotificationSendTestRequest, db: Session = Depends(get_db)) -> NotificationSendTestResponse:
    try:
        job = enqueue_test_notification(db, payload.subscription_id, severity=payload.force_severity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    run_notification_cycle(db)
    return NotificationSendTestResponse(status="queued", job_id=job.id, message="Test notification queued")


@router.get("/delivery-logs", response_model=NotificationDeliveryLogsResponse)
def get_delivery_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> NotificationDeliveryLogsResponse:
    rows = list_delivery_logs(db, limit=limit)
    return NotificationDeliveryLogsResponse(
        items=[
            NotificationDeliveryLogItem(
                id=row.id,
                job_id=row.job_id,
                subscription_id=row.subscription_id,
                channel=row.channel,
                destination=row.destination,
                status=row.status,
                attempt_number=row.attempt_number,
                response_code=row.response_code,
                provider_message=row.provider_message,
                payload=row.payload,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@router.post("/run-once")
def run_once(db: Session = Depends(get_db)) -> dict:
    result = run_notification_cycle(db)
    return {"status": "ok", **result}
