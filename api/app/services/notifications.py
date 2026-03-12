from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import logging
import secrets
import threading
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import (
    NotificationChannelConnection,
    NotificationDeliveryLog,
    NotificationJob,
    NotificationSubscription,
    SevereWeatherEvent,
)
from .features import get_hours_between
from .health import get_or_generate_health_alert
from .ingestion import ingest_hourly_forecast
from .location import get_or_create_location
from .outfit import get_or_generate_outfit
from .plan import get_plan_windows


logger = logging.getLogger(__name__)
SUPPORTED_CHANNELS = {"telegram", "discord", "slack"}
CONNECT_STATUSES = {"pending", "connected", "failed", "expired"}

_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event = threading.Event()
_scheduler_lock = threading.Lock()


@dataclass
class DeliveryResult:
    provider: str
    response_code: int | None
    message: str


def _utc_now() -> datetime:
    return datetime.utcnow()


def _parse_hhmm(value: str) -> time:
    cleaned = (value or "").strip()
    if len(cleaned) != 5 or cleaned[2] != ":":
        raise ValueError(f"Invalid time format '{value}', expected HH:MM")
    hour = int(cleaned[:2])
    minute = int(cleaned[3:])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid time value '{value}'")
    return time(hour=hour, minute=minute)


def _resolve_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _format_destination(channel: str, destination: str) -> str:
    return destination.strip()


def _next_run_at_utc(schedule_time: str, timezone_name: str, now_utc: datetime | None = None) -> datetime:
    now = now_utc or _utc_now()
    tzinfo = _resolve_tz(timezone_name)
    local_now = now.replace(tzinfo=UTC).astimezone(tzinfo)
    local_target_time = _parse_hhmm(schedule_time)
    local_target = local_now.replace(
        hour=local_target_time.hour,
        minute=local_target_time.minute,
        second=0,
        microsecond=0,
    )
    if local_target <= local_now:
        local_target += timedelta(days=1)
    return local_target.astimezone(UTC).replace(tzinfo=None)


def _is_in_quiet_hours(now_utc: datetime, timezone_name: str, quiet_start: str, quiet_end: str) -> bool:
    tzinfo = _resolve_tz(timezone_name)
    local_now = now_utc.replace(tzinfo=UTC).astimezone(tzinfo)
    start = _parse_hhmm(quiet_start)
    end = _parse_hhmm(quiet_end)
    local_time = local_now.time()

    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def _mask_destination(channel: str, destination: str) -> str:
    value = destination.strip()
    if channel == "telegram":
        if len(value) <= 4:
            return "***"
        return f"***{value[-4:]}"
    if channel in {"discord", "slack"}:
        if "://" in value:
            scheme, remainder = value.split("://", 1)
            if "/" in remainder:
                host = remainder.split("/", 1)[0]
                return f"{scheme}://{host}/***"
            return f"{scheme}://***"
        return "***"
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def _default_payload(location_name: str, severity: str) -> dict:
    title = f"Forecast Hub Update · {location_name}"
    if severity == "high":
        title = f"Severe Weather Alert · {location_name}"
    return {
        "title": title,
        "body": "Your personalized weather guidance is ready. Open Forecast Hub for full details.",
    }


def _connect_expiry(now: datetime | None = None) -> datetime:
    current = now or _utc_now()
    return current + timedelta(minutes=max(1, settings.notification_connect_token_ttl_minutes))


def _require_api_base_url() -> str:
    base_url = (settings.forecasthub_api_base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("FORECASTHUB_API_BASE_URL is not configured")
    return base_url


def _resolve_telegram_bot_username() -> str:
    explicit = (settings.telegram_bot_username or "").strip().lstrip("@")
    if explicit:
        return explicit
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    username = ((data.get("result") or {}).get("username") or "").strip()
    if not username:
        raise RuntimeError("Could not resolve Telegram bot username")
    return username


def _build_connect_url(channel: str, token: str) -> tuple[str, str]:
    if channel == "telegram":
        username = _resolve_telegram_bot_username()
        return (
            f"https://t.me/{username}?start={token}",
            "Open the Telegram link, press Start, then return and click Check Connection.",
        )

    base_url = _require_api_base_url()
    if channel == "slack":
        if not settings.slack_client_id or not settings.slack_client_secret:
            raise RuntimeError("SLACK_CLIENT_ID / SLACK_CLIENT_SECRET are not configured")
        redirect_uri = f"{base_url}/v1/notifications/connect/slack/callback"
        query = urlencode(
            {
                "client_id": settings.slack_client_id,
                "scope": "incoming-webhook",
                "redirect_uri": redirect_uri,
                "state": token,
            }
        )
        return (
            f"https://slack.com/oauth/v2/authorize?{query}",
            "Authorize Slack incoming webhook in the opened page, then return and click Check Connection.",
        )

    if channel == "discord":
        if not settings.discord_client_id or not settings.discord_client_secret:
            raise RuntimeError("DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET are not configured")
        redirect_uri = f"{base_url}/v1/notifications/connect/discord/callback"
        query = urlencode(
            {
                "client_id": settings.discord_client_id,
                "response_type": "code",
                "scope": "webhook.incoming",
                "redirect_uri": redirect_uri,
                "state": token,
                "prompt": "consent",
            }
        )
        return (
            f"https://discord.com/oauth2/authorize?{query}",
            "Authorize Discord incoming webhook in the opened page, then return and click Check Connection.",
        )

    raise ValueError(f"Unsupported connect channel '{channel}'")


def get_connect_url_and_instructions(channel: str, token: str) -> tuple[str, str]:
    return _build_connect_url(channel, token)


def _serialize_connect_payload(
    *,
    location_name: str,
    channel: str,
    enabled: bool,
    schedule_time: str,
    timezone_name: str,
    include_outfit: bool,
    include_health: bool,
    include_plan: bool,
    quiet_hours_enabled: bool,
    quiet_start: str,
    quiet_end: str,
    escalation_enabled: bool,
) -> dict:
    return {
        "location_name": location_name.strip(),
        "channel": channel,
        "enabled": bool(enabled),
        "schedule_time": schedule_time,
        "timezone_name": timezone_name,
        "include_outfit": bool(include_outfit),
        "include_health": bool(include_health),
        "include_plan": bool(include_plan),
        "quiet_hours_enabled": bool(quiet_hours_enabled),
        "quiet_start": quiet_start,
        "quiet_end": quiet_end,
        "escalation_enabled": bool(escalation_enabled),
    }


def _get_connection_by_token(db: Session, token: str) -> NotificationChannelConnection | None:
    return (
        db.query(NotificationChannelConnection)
        .filter(NotificationChannelConnection.token == token.strip())
        .first()
    )


def _mark_connection_expired_if_needed(db: Session, connection: NotificationChannelConnection, now: datetime) -> None:
    if connection.status in {"connected", "failed", "expired"}:
        return
    if connection.expires_at <= now:
        connection.status = "expired"
        connection.error_message = "Connection token expired. Please start again."
        db.commit()


def start_channel_connection(
    db: Session,
    *,
    location_name: str,
    channel: str,
    enabled: bool,
    schedule_time: str,
    timezone_name: str,
    include_outfit: bool,
    include_health: bool,
    include_plan: bool,
    quiet_hours_enabled: bool,
    quiet_start: str,
    quiet_end: str,
    escalation_enabled: bool,
) -> NotificationChannelConnection:
    if channel not in SUPPORTED_CHANNELS:
        raise ValueError(f"Unsupported notification channel '{channel}'")

    _parse_hhmm(schedule_time)
    _parse_hhmm(quiet_start)
    _parse_hhmm(quiet_end)
    _resolve_tz(timezone_name)

    now = _utc_now()
    payload = _serialize_connect_payload(
        location_name=location_name,
        channel=channel,
        enabled=enabled,
        schedule_time=schedule_time,
        timezone_name=timezone_name,
        include_outfit=include_outfit,
        include_health=include_health,
        include_plan=include_plan,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        escalation_enabled=escalation_enabled,
    )
    token = secrets.token_urlsafe(24)
    connection = NotificationChannelConnection(
        channel=channel,
        token=token,
        status="pending",
        payload=payload,
        expires_at=_connect_expiry(now),
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def get_channel_connection_status(db: Session, token: str) -> NotificationChannelConnection | None:
    connection = _get_connection_by_token(db, token)
    if connection is None:
        return None
    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    return connection


def _fail_channel_connection(db: Session, connection: NotificationChannelConnection, message: str) -> NotificationChannelConnection:
    connection.status = "failed"
    connection.error_message = message
    connection.used_at = _utc_now()
    db.commit()
    db.refresh(connection)
    return connection


def complete_channel_connection(
    db: Session,
    *,
    token: str,
    destination: str,
) -> NotificationChannelConnection:
    connection = _get_connection_by_token(db, token)
    if connection is None:
        raise ValueError("Connection token not found")

    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    if connection.status == "expired":
        return connection
    if connection.status == "connected":
        return connection
    if connection.status == "failed":
        return connection

    payload = connection.payload or {}
    try:
        row = create_or_update_subscription(
            db,
            location_name=str(payload.get("location_name") or ""),
            channel=str(payload.get("channel") or connection.channel),
            destination=destination,
            enabled=bool(payload.get("enabled", True)),
            schedule_time=str(payload.get("schedule_time") or "08:00"),
            timezone_name=str(payload.get("timezone_name") or "UTC"),
            include_outfit=bool(payload.get("include_outfit", True)),
            include_health=bool(payload.get("include_health", True)),
            include_plan=bool(payload.get("include_plan", True)),
            quiet_hours_enabled=bool(payload.get("quiet_hours_enabled", False)),
            quiet_start=str(payload.get("quiet_start") or "22:00"),
            quiet_end=str(payload.get("quiet_end") or "07:00"),
            escalation_enabled=bool(payload.get("escalation_enabled", True)),
        )
    except Exception as exc:
        return _fail_channel_connection(db, connection, f"Failed to save channel connection: {exc}")

    connection.status = "connected"
    connection.destination = destination
    connection.subscription_id = row.id
    connection.used_at = _utc_now()
    connection.error_message = None
    db.commit()
    db.refresh(connection)
    return connection


def complete_telegram_connection_from_updates(db: Session, token: str) -> NotificationChannelConnection:
    connection = _get_connection_by_token(db, token)
    if connection is None:
        raise ValueError("Connection token not found")
    if connection.channel != "telegram":
        raise ValueError("Connection token is not for Telegram")
    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    if connection.status in {"connected", "failed", "expired"}:
        return connection
    if not settings.telegram_bot_token:
        return _fail_channel_connection(db, connection, "TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    updates = data.get("result") or []
    for update in reversed(updates):
        message = update.get("message") or update.get("edited_message") or {}
        text = str(message.get("text") or "")
        if not text.startswith("/start"):
            continue
        parts = text.split(maxsplit=1)
        payload_token = parts[1].strip() if len(parts) > 1 else ""
        if payload_token != token:
            continue
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        return complete_channel_connection(db, token=token, destination=str(chat_id))

    return connection


def complete_slack_connection_from_code(db: Session, token: str, code: str) -> NotificationChannelConnection:
    connection = _get_connection_by_token(db, token)
    if connection is None:
        raise ValueError("Connection token not found")
    if connection.channel != "slack":
        raise ValueError("Connection token is not for Slack")
    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    if connection.status in {"connected", "failed", "expired"}:
        return connection
    if not settings.slack_client_id or not settings.slack_client_secret:
        return _fail_channel_connection(db, connection, "SLACK_CLIENT_ID / SLACK_CLIENT_SECRET are not configured")

    redirect_uri = f"{_require_api_base_url()}/v1/notifications/connect/slack/callback"
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": settings.slack_client_id,
                "client_secret": settings.slack_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        data = response.json()
    if not data.get("ok"):
        return _fail_channel_connection(db, connection, f"Slack OAuth failed: {data.get('error') or 'unknown_error'}")

    webhook_url = ((data.get("incoming_webhook") or {}).get("url") or "").strip()
    if not webhook_url:
        return _fail_channel_connection(db, connection, "Slack OAuth did not return incoming webhook URL")
    return complete_channel_connection(db, token=token, destination=webhook_url)


def complete_discord_connection_from_code(db: Session, token: str, code: str) -> NotificationChannelConnection:
    connection = _get_connection_by_token(db, token)
    if connection is None:
        raise ValueError("Connection token not found")
    if connection.channel != "discord":
        raise ValueError("Connection token is not for Discord")
    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    if connection.status in {"connected", "failed", "expired"}:
        return connection
    if not settings.discord_client_id or not settings.discord_client_secret:
        return _fail_channel_connection(db, connection, "DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET are not configured")

    redirect_uri = f"{_require_api_base_url()}/v1/notifications/connect/discord/callback"
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()

    webhook = data.get("webhook") or {}
    webhook_url = (webhook.get("url") or "").strip()
    if not webhook_url:
        webhook_id = webhook.get("id")
        webhook_token = webhook.get("token")
        if webhook_id and webhook_token:
            webhook_url = f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
    if not webhook_url:
        return _fail_channel_connection(db, connection, "Discord OAuth did not return webhook URL")
    return complete_channel_connection(db, token=token, destination=webhook_url)


def _build_daily_payload(db: Session, subscription: NotificationSubscription, severity: str, reason: str | None = None) -> dict:
    now = _utc_now()
    location = get_or_create_location(db, subscription.location_name)
    hours = get_hours_between(db, location.id, now, now + timedelta(hours=24))
    if not hours:
        try:
            ingest_hourly_forecast(db, location)
        except Exception as exc:
            logger.warning("Notification payload fetch fallback failed for %s: %s", location.name, exc)
        hours = get_hours_between(db, location.id, now, now + timedelta(hours=24))

    if not hours:
        return _default_payload(location.name, severity)

    current_temp = hours[0].temperature_c
    next_hour_temp = hours[1].temperature_c if len(hours) > 1 else current_temp
    precip_total = sum((h.precipitation_mm or 0.0) for h in hours)
    max_wind = max((h.wind_speed_kph or 0.0) for h in hours)

    today = now.date()
    lines = [
        f"{location.name}: now {current_temp:.1f} C, next hour {next_hour_temp:.1f} C."
        if current_temp is not None and next_hour_temp is not None
        else f"{location.name}: latest forecast refreshed.",
        f"24h precipitation {precip_total:.1f} mm, max wind {max_wind:.1f} kph.",
    ]

    if subscription.include_plan:
        plan_rows = get_plan_windows(db, location.id, today)
        if plan_rows:
            top = sorted(plan_rows, key=lambda row: row.score, reverse=True)[:2]
            lines.append(
                "Best windows: "
                + "; ".join([f"{row.category} around {row.best_hour:02d}:00 ({row.score:.0f}/100)" for row in top])
                + "."
            )

    if subscription.include_outfit:
        outfit = get_or_generate_outfit(db, location.id, today)
        if outfit:
            lines.append(f"Outfit: {outfit.summary}")

    if subscription.include_health:
        health = get_or_generate_health_alert(db, location.id, today)
        if health:
            lines.append(
                f"Health: heat {health.heat_risk}/100, dehydration {health.dehydration_risk}/100, asthma {health.asthma_proxy_risk}/100."
            )

    title = f"Forecast Hub Daily Brief · {location.name}"
    if severity == "high":
        title = f"Severe Weather Alert · {location.name}"
        if reason:
            lines.insert(0, f"High-risk condition detected: {reason}")

    return {"title": title, "body": " ".join(lines)}


def list_subscriptions(db: Session) -> list[NotificationSubscription]:
    return db.query(NotificationSubscription).order_by(NotificationSubscription.created_at.desc()).all()


def create_or_update_subscription(
    db: Session,
    *,
    location_name: str,
    channel: str,
    destination: str,
    enabled: bool,
    schedule_time: str,
    timezone_name: str,
    include_outfit: bool,
    include_health: bool,
    include_plan: bool,
    quiet_hours_enabled: bool,
    quiet_start: str,
    quiet_end: str,
    escalation_enabled: bool,
) -> NotificationSubscription:
    if channel not in SUPPORTED_CHANNELS:
        raise ValueError(f"Unsupported notification channel '{channel}'")

    _parse_hhmm(schedule_time)
    _parse_hhmm(quiet_start)
    _parse_hhmm(quiet_end)

    normalized_destination = _format_destination(channel, destination)
    normalized_location = location_name.strip()

    existing = (
        db.query(NotificationSubscription)
        .filter(
            NotificationSubscription.channel == channel,
            NotificationSubscription.destination == normalized_destination,
            NotificationSubscription.location_name == normalized_location,
        )
        .first()
    )

    next_run_at = _next_run_at_utc(schedule_time, timezone_name)

    if existing:
        existing.enabled = enabled
        existing.schedule_time = schedule_time
        existing.timezone = timezone_name
        existing.include_outfit = include_outfit
        existing.include_health = include_health
        existing.include_plan = include_plan
        existing.quiet_hours_enabled = quiet_hours_enabled
        existing.quiet_start = quiet_start
        existing.quiet_end = quiet_end
        existing.escalation_enabled = escalation_enabled
        existing.next_run_at = next_run_at
        db.commit()
        db.refresh(existing)
        return existing

    row = NotificationSubscription(
        location_name=normalized_location,
        channel=channel,
        destination=normalized_destination,
        enabled=enabled,
        schedule_time=schedule_time,
        timezone=timezone_name,
        include_outfit=include_outfit,
        include_health=include_health,
        include_plan=include_plan,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        escalation_enabled=escalation_enabled,
        next_run_at=next_run_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_subscription(db: Session, subscription_id: int, **updates) -> NotificationSubscription | None:
    row = db.query(NotificationSubscription).filter(NotificationSubscription.id == subscription_id).first()
    if row is None:
        return None

    for key, value in updates.items():
        if value is None:
            continue
        setattr(row, key, value)

    if updates.get("schedule_time") or updates.get("timezone"):
        schedule_time = row.schedule_time
        timezone_name = row.timezone
        _parse_hhmm(schedule_time)
        row.next_run_at = _next_run_at_utc(schedule_time, timezone_name)

    if updates.get("quiet_start"):
        _parse_hhmm(row.quiet_start)
    if updates.get("quiet_end"):
        _parse_hhmm(row.quiet_end)

    db.commit()
    db.refresh(row)
    return row


def delete_subscription(db: Session, subscription_id: int) -> bool:
    row = db.query(NotificationSubscription).filter(NotificationSubscription.id == subscription_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _enqueue_job(
    db: Session,
    *,
    subscription: NotificationSubscription,
    payload: dict,
    severity: str,
    dedupe_key: str,
    next_attempt_at: datetime,
) -> NotificationJob | None:
    row = NotificationJob(
        subscription_id=subscription.id,
        status="pending",
        severity=severity,
        attempt_count=0,
        max_attempts=max(1, settings.notification_max_retries + 1),
        next_attempt_at=next_attempt_at,
        dedupe_key=dedupe_key,
        payload=payload,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        return None


def enqueue_test_notification(db: Session, subscription_id: int, severity: str = "normal") -> NotificationJob:
    subscription = (
        db.query(NotificationSubscription)
        .filter(NotificationSubscription.id == subscription_id)
        .first()
    )
    if subscription is None:
        raise ValueError("Subscription not found")
    if subscription.channel not in SUPPORTED_CHANNELS:
        raise ValueError(f"Unsupported notification channel '{subscription.channel}'")

    payload = _build_daily_payload(db, subscription, severity=severity, reason="manual test")
    dedupe_key = f"test:{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    job = _enqueue_job(
        db,
        subscription=subscription,
        payload=payload,
        severity=severity,
        dedupe_key=dedupe_key,
        next_attempt_at=_utc_now(),
    )
    if job is None:
        raise RuntimeError("Unable to enqueue test notification")
    return job


def list_delivery_logs(db: Session, limit: int = 100) -> list[NotificationDeliveryLog]:
    return (
        db.query(NotificationDeliveryLog)
        .order_by(NotificationDeliveryLog.created_at.desc())
        .limit(limit)
        .all()
    )


def _deliver_telegram(destination: str, body: str) -> DeliveryResult:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": destination, "text": body}
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    ok = data.get("ok")
    if not ok:
        raise RuntimeError(f"Telegram send failed: {data}")
    return DeliveryResult(provider="telegram", response_code=response.status_code, message="sent")


def _deliver_discord(destination: str, body: str) -> DeliveryResult:
    payload = {"content": body}
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(destination, json=payload)
        response.raise_for_status()
    return DeliveryResult(provider="discord_webhook", response_code=response.status_code, message="sent")


def _deliver_slack(destination: str, body: str) -> DeliveryResult:
    payload = {"text": body}
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(destination, json=payload)
        response.raise_for_status()
    return DeliveryResult(provider="slack_webhook", response_code=response.status_code, message="sent")


def _deliver(subscription: NotificationSubscription, payload: dict) -> DeliveryResult:
    title = str(payload.get("title") or "Forecast Hub Notification")
    body = str(payload.get("body") or "Your forecast update is ready.")
    text = f"{title}\n\n{body}"
    if subscription.channel == "telegram":
        return _deliver_telegram(subscription.destination, text)
    if subscription.channel == "discord":
        return _deliver_discord(subscription.destination, text)
    if subscription.channel == "slack":
        return _deliver_slack(subscription.destination, text)
    raise RuntimeError(f"Unsupported channel '{subscription.channel}'")


def _next_retry_time(now: datetime, attempt_count: int) -> datetime:
    retry_steps = settings.notification_retry_backoff
    index = min(max(0, attempt_count - 1), len(retry_steps) - 1)
    return now + timedelta(seconds=retry_steps[index])


def _log_delivery_attempt(
    db: Session,
    *,
    job: NotificationJob,
    subscription: NotificationSubscription,
    status: str,
    attempt_number: int,
    response_code: int | None,
    provider_message: str | None,
) -> None:
    row = NotificationDeliveryLog(
        job_id=job.id,
        subscription_id=subscription.id,
        channel=subscription.channel,
        destination=_mask_destination(subscription.channel, subscription.destination),
        status=status,
        attempt_number=attempt_number,
        response_code=response_code,
        provider_message=provider_message,
        payload=job.payload,
    )
    db.add(row)


def _enqueue_due_daily_jobs(db: Session, now: datetime) -> int:
    due_subscriptions = (
        db.query(NotificationSubscription)
        .filter(
            NotificationSubscription.enabled.is_(True),
            NotificationSubscription.channel.in_(SUPPORTED_CHANNELS),
            NotificationSubscription.next_run_at.is_not(None),
            NotificationSubscription.next_run_at <= now,
        )
        .all()
    )
    created = 0
    for subscription in due_subscriptions:
        if subscription.quiet_hours_enabled and _is_in_quiet_hours(
            now,
            subscription.timezone,
            subscription.quiet_start,
            subscription.quiet_end,
        ):
            subscription.next_run_at = now + timedelta(minutes=30)
            db.commit()
            continue

        local_now = now.replace(tzinfo=UTC).astimezone(_resolve_tz(subscription.timezone))
        dedupe_key = f"daily:{local_now.date().isoformat()}"
        payload = _build_daily_payload(db, subscription, severity="normal")
        job = _enqueue_job(
            db,
            subscription=subscription,
            payload=payload,
            severity="normal",
            dedupe_key=dedupe_key,
            next_attempt_at=now,
        )
        if job:
            created += 1
        subscription.next_run_at = _next_run_at_utc(subscription.schedule_time, subscription.timezone, now_utc=now)
        db.commit()
    return created


def _is_severe_weather(db: Session, location_name: str, now: datetime) -> tuple[bool, str]:
    location = get_or_create_location(db, location_name)
    hours = get_hours_between(db, location.id, now, now + timedelta(hours=24))
    if not hours:
        try:
            ingest_hourly_forecast(db, location)
        except Exception:
            return False, ""
        hours = get_hours_between(db, location.id, now, now + timedelta(hours=24))
    if not hours:
        return False, ""

    precipitation_total = sum((h.precipitation_mm or 0.0) for h in hours)
    max_wind = max((h.wind_speed_kph or 0.0) for h in hours)
    today = now.date()
    health = get_or_generate_health_alert(db, location.id, today)
    health_risk = 0
    if health:
        health_risk = max(
            health.heat_risk,
            health.cold_risk,
            health.dehydration_risk,
            health.asthma_proxy_risk,
        )

    reasons: list[str] = []
    if health_risk >= settings.severe_risk_threshold:
        reasons.append(f"health risk {health_risk}/100")
    if precipitation_total >= settings.severe_precip_threshold_mm:
        reasons.append(f"high rain {precipitation_total:.1f} mm")
    if max_wind >= settings.severe_wind_threshold_kph:
        reasons.append(f"high wind {max_wind:.1f} kph")

    if reasons:
        return True, ", ".join(reasons)
    return False, ""


def _enqueue_severe_escalations(db: Session, now: datetime) -> int:
    subscriptions = (
        db.query(NotificationSubscription)
        .filter(
            NotificationSubscription.enabled.is_(True),
            NotificationSubscription.escalation_enabled.is_(True),
            NotificationSubscription.channel.in_(SUPPORTED_CHANNELS),
        )
        .all()
    )
    if not subscriptions:
        return 0

    by_location: dict[str, list[NotificationSubscription]] = {}
    for subscription in subscriptions:
        by_location.setdefault(subscription.location_name, []).append(subscription)

    created = 0
    cooldown_cutoff = now - timedelta(minutes=settings.severe_escalation_cooldown_minutes)
    for location_name, location_subscriptions in by_location.items():
        severe, reason = _is_severe_weather(db, location_name, now)
        if not severe:
            continue

        location = get_or_create_location(db, location_name)
        recent = (
            db.query(SevereWeatherEvent)
            .filter(
                SevereWeatherEvent.location_id == location.id,
                SevereWeatherEvent.created_at >= cooldown_cutoff,
            )
            .first()
        )
        if recent:
            continue

        event = SevereWeatherEvent(location_id=location.id, severity="high", reason=reason)
        db.add(event)
        db.commit()
        db.refresh(event)

        for subscription in location_subscriptions:
            payload = _build_daily_payload(db, subscription, severity="high", reason=reason)
            job = _enqueue_job(
                db,
                subscription=subscription,
                payload=payload,
                severity="high",
                dedupe_key=f"severe:{event.id}",
                next_attempt_at=now,
            )
            if job:
                created += 1
    return created


def _process_due_jobs(db: Session, now: datetime) -> int:
    jobs = (
        db.query(NotificationJob)
        .filter(
            NotificationJob.status.in_(["pending", "retrying"]),
            NotificationJob.next_attempt_at <= now,
        )
        .order_by(NotificationJob.severity.desc(), NotificationJob.next_attempt_at.asc())
        .limit(settings.notification_job_batch_size)
        .all()
    )
    processed = 0
    for job in jobs:
        subscription = (
            db.query(NotificationSubscription)
            .filter(NotificationSubscription.id == job.subscription_id)
            .first()
        )
        if subscription is None or not subscription.enabled:
            job.status = "failed"
            job.last_error = "Subscription not found or disabled"
            db.commit()
            processed += 1
            continue

        attempt_number = job.attempt_count + 1
        try:
            result = _deliver(subscription, job.payload or {})
            job.status = "sent"
            job.attempt_count = attempt_number
            job.delivered_at = now
            job.last_error = None
            subscription.last_sent_at = now
            _log_delivery_attempt(
                db,
                job=job,
                subscription=subscription,
                status="sent",
                attempt_number=attempt_number,
                response_code=result.response_code,
                provider_message=result.message,
            )
            db.commit()
        except Exception as exc:
            job.attempt_count = attempt_number
            error_message = str(exc)
            if attempt_number >= job.max_attempts:
                job.status = "failed"
                job.last_error = error_message
            else:
                job.status = "retrying"
                job.last_error = error_message
                job.next_attempt_at = _next_retry_time(now, attempt_number)
            _log_delivery_attempt(
                db,
                job=job,
                subscription=subscription,
                status=job.status,
                attempt_number=attempt_number,
                response_code=None,
                provider_message=error_message,
            )
            db.commit()
            logger.warning(
                "Notification delivery failed job_id=%s attempt=%s/%s channel=%s destination=%s error=%s",
                job.id,
                attempt_number,
                job.max_attempts,
                subscription.channel,
                _mask_destination(subscription.channel, subscription.destination),
                error_message,
            )
        processed += 1
    return processed


def run_notification_cycle(db: Session) -> dict:
    now = _utc_now()
    scheduled = _enqueue_due_daily_jobs(db, now)
    escalations = _enqueue_severe_escalations(db, now)
    processed = _process_due_jobs(db, now)
    return {
        "scheduled_jobs": scheduled,
        "escalation_jobs": escalations,
        "processed_jobs": processed,
    }


def start_notification_scheduler() -> None:
    if not settings.notification_scheduler_enabled:
        logger.info("Notification scheduler disabled by configuration")
        return

    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return

        _scheduler_stop_event.clear()

        def _run() -> None:
            logger.info("Notification scheduler started (interval=%ss)", settings.notification_scheduler_interval_seconds)
            while not _scheduler_stop_event.is_set():
                try:
                    with SessionLocal() as db:
                        run_notification_cycle(db)
                except Exception as exc:
                    logger.exception("Notification scheduler tick failed: %s", exc)
                _scheduler_stop_event.wait(settings.notification_scheduler_interval_seconds)
            logger.info("Notification scheduler stopped")

        _scheduler_thread = threading.Thread(target=_run, name="notification-scheduler", daemon=True)
        _scheduler_thread.start()


def stop_notification_scheduler() -> None:
    with _scheduler_lock:
        if _scheduler_thread is None:
            return
        _scheduler_stop_event.set()
