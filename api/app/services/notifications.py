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
    NotificationProviderState,
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
TELEGRAM_PROVIDER_STATE_KEY = "telegram"

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


def _format_subscription_details(subscription: NotificationSubscription) -> str:
    included_sections: list[str] = []
    if subscription.include_outfit:
        included_sections.append("outfit")
    if subscription.include_health:
        included_sections.append("health")
    if subscription.include_plan:
        included_sections.append("plan")
    include_text = ", ".join(included_sections) if included_sections else "none"

    if subscription.quiet_hours_enabled:
        quiet_text = f"{subscription.quiet_start}-{subscription.quiet_end}"
    else:
        quiet_text = "off"

    escalation_text = "on" if subscription.escalation_enabled else "off"
    return (
        "Subscription details: "
        f"location {subscription.location_name}; "
        f"daily time {subscription.schedule_time} ({subscription.timezone}); "
        f"sections {include_text}; "
        f"quiet hours {quiet_text}; "
        f"severe escalation {escalation_text}."
    )


def _format_message_section(title: str, entries: list[str]) -> str:
    cleaned = [entry.strip() for entry in entries if entry and entry.strip()]
    if not cleaned:
        return ""
    bullets = "\n".join([f"- {entry}" for entry in cleaned])
    return f"{title}\n{bullets}"


def _fallback_wear_tip(current_temp: float | None) -> str:
    if current_temp is None:
        return "Wear comfortable layers and check live conditions before heading out."
    if current_temp <= 5:
        return "Wear a warm jacket with an extra insulating layer."
    if current_temp <= 16:
        return "Wear light layers or a hoodie for comfort."
    if current_temp <= 28:
        return "Wear breathable daywear with one optional outer layer."
    return "Wear lightweight clothing and stay hydrated."


def _fallback_shoe_tip(precip_total: float, current_temp: float | None) -> str:
    if precip_total >= 4:
        return "Water-resistant shoes"
    if current_temp is not None and current_temp <= 5:
        return "Closed, warm shoes"
    return "Comfortable sneakers"


def _fallback_sunscreen_tip(max_uv: float) -> str:
    if max_uv >= 6:
        return "Required (SPF 30+)"
    if max_uv >= 3:
        return "Recommended (SPF 15+)"
    return "Optional"


def _telegram_settings_help_text() -> str:
    return (
        "Telegram controls:\n"
        "/status - current subscription settings\n"
        "/settime HH:MM - set daily notification time\n"
        "/settimezone Area/City - set timezone (example: America/Chicago)\n"
        "/quiet on|off - enable/disable quiet hours\n"
        "/quiethours HH:MM HH:MM - set quiet hours window\n"
        "/include outfit|health|plan on|off - toggle sections\n"
        "/escalation on|off - severe weather escalation\n"
        "/setlocation City Name - change location\n"
        "/help - show this command list"
    )


def _build_connect_sample_payload(db: Session, subscription: NotificationSubscription) -> dict:
    now = _utc_now()
    location = get_or_create_location(db, subscription.location_name)
    hours = get_hours_between(db, location.id, now, now + timedelta(hours=24))
    if not hours:
        try:
            ingest_hourly_forecast(db, location)
        except Exception as exc:
            logger.warning("Connect sample payload fetch fallback failed for %s: %s", location.name, exc)
        hours = get_hours_between(db, location.id, now, now + timedelta(hours=24))

    details = _format_subscription_details(subscription)
    if not hours:
        return {
            "title": f"Sample Weather Suggestion · {location.name}",
            "body": (
                "Sample suggestion: check hourly updates before leaving and keep one extra layer ready. "
                + details
            ),
        }

    current_temp = hours[0].temperature_c
    next_hour_temp = hours[1].temperature_c if len(hours) > 1 else current_temp
    precipitation_total = sum((h.precipitation_mm or 0.0) for h in hours)
    max_wind = max((h.wind_speed_kph or 0.0) for h in hours)
    max_uv = max((h.uv_index or 0.0) for h in hours)
    outfit = get_or_generate_outfit(db, location.id, now.date())

    wear_line = outfit.summary if outfit else _fallback_wear_tip(current_temp)
    umbrella_line = (
        "Yes" if outfit and outfit.umbrella else ("Yes" if precipitation_total >= 4 else "No")
    )
    shoes_line = outfit.shoes if outfit else _fallback_shoe_tip(precipitation_total, current_temp)
    sunscreen_line = outfit.sunscreen if outfit else _fallback_sunscreen_tip(max_uv)

    sections = [
        _format_message_section(
            "What to Wear",
            [
                wear_line,
                f"Umbrella: {umbrella_line}",
                f"Shoes: {shoes_line}",
                f"Sunscreen: {sunscreen_line}",
            ],
        ),
        _format_message_section(
            "Detailed Forecast",
            [
                f"Location: {location.name}",
                f"Now: {current_temp:.1f} C" if current_temp is not None else "Now: n/a",
                f"Next hour: {next_hour_temp:.1f} C" if next_hour_temp is not None else "Next hour: n/a",
                f"24h precipitation: {precipitation_total:.1f} mm",
                f"Max wind: {max_wind:.1f} kph",
                f"Max UV: {max_uv:.1f}",
            ],
        ),
        _format_message_section("Subscription", [details]),
    ]
    return {
        "title": f"Sample Weather Suggestion · {location.name}",
        "body": "\n\n".join([section for section in sections if section]),
    }


def _send_connect_welcome_messages(db: Session, subscription: NotificationSubscription) -> None:
    details = _format_subscription_details(subscription)
    test_payload = {
        "title": "Forecast Hub Connected",
        "body": (
            "Test message: your channel connection is active and notifications are enabled. "
            + details
        ),
    }
    _deliver(subscription, test_payload)

    sample_payload = _build_connect_sample_payload(db, subscription)
    _deliver(subscription, sample_payload)
    if subscription.channel == "telegram":
        _deliver(
            subscription,
            {
                "title": "Manage Settings From Telegram",
                "body": _telegram_settings_help_text(),
            },
        )


def _get_or_create_provider_state(db: Session, provider: str) -> NotificationProviderState:
    state = (
        db.query(NotificationProviderState)
        .filter(NotificationProviderState.provider == provider)
        .first()
    )
    if state is not None:
        return state
    state = NotificationProviderState(provider=provider, last_update_id=0)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _parse_on_off(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    raise ValueError("Use 'on' or 'off'.")


def _validate_timezone_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Timezone is required.")
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone '{value}'.") from exc
    return cleaned


def _format_subscription_status_lines(subscriptions: list[NotificationSubscription]) -> str:
    lines = ["Current Forecast Hub settings:"]
    for index, subscription in enumerate(subscriptions, start=1):
        include_sections: list[str] = []
        if subscription.include_outfit:
            include_sections.append("outfit")
        if subscription.include_health:
            include_sections.append("health")
        if subscription.include_plan:
            include_sections.append("plan")
        include_text = ", ".join(include_sections) if include_sections else "none"
        quiet_text = (
            f"{subscription.quiet_start}-{subscription.quiet_end}"
            if subscription.quiet_hours_enabled
            else "off"
        )
        escalation_text = "on" if subscription.escalation_enabled else "off"
        lines.append(
            f"{index}) {subscription.location_name} | time {subscription.schedule_time} ({subscription.timezone}) | "
            f"include {include_text} | quiet {quiet_text} | escalation {escalation_text}"
        )
    return "\n".join(lines)


def _handle_telegram_settings_command(
    db: Session,
    *,
    chat_id: str,
    text: str,
) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split()
    command = parts[0].split("@", 1)[0].lower()
    args = parts[1:]

    supported_commands = {
        "/help",
        "/status",
        "/settime",
        "/settimezone",
        "/quiet",
        "/quiethours",
        "/include",
        "/escalation",
        "/setlocation",
    }
    if command not in supported_commands:
        return None

    subscriptions = (
        db.query(NotificationSubscription)
        .filter(
            NotificationSubscription.channel == "telegram",
            NotificationSubscription.destination == chat_id,
        )
        .order_by(NotificationSubscription.id.asc())
        .all()
    )

    if command == "/help":
        return _telegram_settings_help_text()

    if not subscriptions:
        return (
            "No Forecast Hub Telegram subscription is linked to this chat yet. "
            "Connect Telegram from the app first."
        )

    try:
        if command == "/status":
            return _format_subscription_status_lines(subscriptions)

        if command == "/settime":
            if len(args) != 1:
                return "Usage: /settime HH:MM"
            schedule_time = args[0].strip()
            _parse_hhmm(schedule_time)
            for subscription in subscriptions:
                subscription.schedule_time = schedule_time
                subscription.next_run_at = _next_run_at_utc(schedule_time, subscription.timezone)
            db.commit()
            return f"Updated daily time to {schedule_time} for {len(subscriptions)} subscription(s)."

        if command == "/settimezone":
            if len(args) != 1:
                return "Usage: /settimezone Area/City"
            timezone_name = _validate_timezone_name(args[0])
            for subscription in subscriptions:
                subscription.timezone = timezone_name
                subscription.next_run_at = _next_run_at_utc(subscription.schedule_time, timezone_name)
            db.commit()
            return f"Updated timezone to {timezone_name} for {len(subscriptions)} subscription(s)."

        if command == "/quiet":
            if len(args) != 1:
                return "Usage: /quiet on|off"
            enabled = _parse_on_off(args[0])
            for subscription in subscriptions:
                subscription.quiet_hours_enabled = enabled
            db.commit()
            return f"Quiet hours {'enabled' if enabled else 'disabled'} for {len(subscriptions)} subscription(s)."

        if command == "/quiethours":
            if len(args) != 2:
                return "Usage: /quiethours HH:MM HH:MM"
            start = args[0].strip()
            end = args[1].strip()
            _parse_hhmm(start)
            _parse_hhmm(end)
            for subscription in subscriptions:
                subscription.quiet_hours_enabled = True
                subscription.quiet_start = start
                subscription.quiet_end = end
            db.commit()
            return f"Updated quiet hours to {start}-{end} for {len(subscriptions)} subscription(s)."

        if command == "/include":
            if len(args) != 2:
                return "Usage: /include outfit|health|plan on|off"
            section = args[0].strip().lower()
            enabled = _parse_on_off(args[1])
            if section not in {"outfit", "health", "plan"}:
                return "Section must be one of: outfit, health, plan."
            for subscription in subscriptions:
                if section == "outfit":
                    subscription.include_outfit = enabled
                elif section == "health":
                    subscription.include_health = enabled
                elif section == "plan":
                    subscription.include_plan = enabled
            db.commit()
            return f"Section '{section}' {'enabled' if enabled else 'disabled'} for {len(subscriptions)} subscription(s)."

        if command == "/escalation":
            if len(args) != 1:
                return "Usage: /escalation on|off"
            enabled = _parse_on_off(args[0])
            for subscription in subscriptions:
                subscription.escalation_enabled = enabled
            db.commit()
            return f"Severe weather escalation {'enabled' if enabled else 'disabled'} for {len(subscriptions)} subscription(s)."

        if command == "/setlocation":
            if not args:
                return "Usage: /setlocation City Name"
            location_name = " ".join(args).strip()
            get_or_create_location(db, location_name)
            for subscription in subscriptions:
                subscription.location_name = location_name
            db.commit()
            return f"Updated location to {location_name} for {len(subscriptions)} subscription(s)."
    except ValueError as exc:
        db.rollback()
        return str(exc)
    except Exception as exc:
        db.rollback()
        logger.exception("Telegram settings command failed chat_id=%s command=%s: %s", chat_id, command, exc)
        return "Unable to apply that command right now. Try again shortly."

    return None


def _process_telegram_settings_commands(db: Session) -> int:
    if not settings.telegram_bot_token:
        return 0

    state = _get_or_create_provider_state(db, TELEGRAM_PROVIDER_STATE_KEY)
    last_update_id = state.last_update_id or 0

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.get(
            url,
            params={
                "offset": last_update_id + 1,
                "timeout": 0,
                "allowed_updates": '["message","edited_message"]',
            },
        )
        response.raise_for_status()
        data = response.json()

    updates = data.get("result") or []
    if not updates:
        return 0

    processed_commands = 0
    max_update_id = last_update_id
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            max_update_id = max(max_update_id, update_id)

        message = update.get("message") or update.get("edited_message") or {}
        text = str(message.get("text") or "")
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue

        response_text = _handle_telegram_settings_command(db, chat_id=str(chat_id), text=text)
        if not response_text:
            continue

        try:
            _deliver_telegram(str(chat_id), response_text)
            processed_commands += 1
        except Exception as exc:
            logger.warning("Failed sending Telegram command response to chat_id=%s: %s", chat_id, exc)

    if max_update_id > last_update_id:
        state.last_update_id = max_update_id
        db.commit()

    return processed_commands


def _connect_expiry(now: datetime | None = None) -> datetime:
    current = now or _utc_now()
    return current + timedelta(minutes=max(1, settings.notification_connect_token_ttl_minutes))


def _require_api_base_url() -> str:
    base_url = (settings.runtime_forecasthub_api_base_url or "").strip().rstrip("/")
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

    try:
        _send_connect_welcome_messages(db, row)
    except Exception as exc:
        # Keep the channel connected, but expose why the immediate test/sample push failed.
        logger.warning(
            "Connected channel but failed immediate welcome send for subscription_id=%s: %s",
            row.id,
            exc,
        )
        connection.error_message = f"Connected, but immediate test messages failed: {exc}"
        db.commit()
        db.refresh(connection)

    return connection


def _complete_telegram_connection_for_start_message(
    db: Session,
    *,
    token: str,
    chat_id: str,
    message_dt: datetime | None,
) -> NotificationChannelConnection | None:
    connection = _get_connection_by_token(db, token)
    if connection is None or connection.channel != "telegram":
        return None

    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    if connection.status in {"failed", "expired"}:
        return connection

    if connection.status == "connected":
        if connection.destination and connection.destination != chat_id:
            # Ignore /start from a different chat for an already bound token.
            return connection

        # Re-send only when /start is newer than the last successful use marker.
        if connection.used_at and message_dt and message_dt <= connection.used_at:
            return connection

        subscription = None
        if connection.subscription_id is not None:
            subscription = (
                db.query(NotificationSubscription)
                .filter(NotificationSubscription.id == connection.subscription_id)
                .first()
            )
        if subscription is None:
            return connection

        try:
            _send_connect_welcome_messages(db, subscription)
            connection.error_message = None
        except Exception as exc:
            logger.warning(
                "Connected Telegram re-start message send failed for subscription_id=%s: %s",
                subscription.id,
                exc,
            )
            connection.error_message = f"Connected, but immediate test messages failed: {exc}"
        connection.used_at = _utc_now()
        db.commit()
        db.refresh(connection)
        return connection

    return complete_channel_connection(db, token=token, destination=chat_id)


def complete_telegram_connection_from_updates(db: Session, token: str) -> NotificationChannelConnection:
    connection = _get_connection_by_token(db, token)
    if connection is None:
        raise ValueError("Connection token not found")
    if connection.channel != "telegram":
        raise ValueError("Connection token is not for Telegram")
    _mark_connection_expired_if_needed(db, connection, _utc_now())
    db.refresh(connection)
    if connection.status in {"failed", "expired"}:
        return connection
    if not settings.telegram_bot_token:
        if connection.status == "connected":
            connection.error_message = "Connected, but TELEGRAM_BOT_TOKEN is not configured for immediate messaging."
            db.commit()
            db.refresh(connection)
            return connection
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
        message_epoch = message.get("date")
        message_dt = None
        if isinstance(message_epoch, (int, float)):
            try:
                message_dt = datetime.utcfromtimestamp(float(message_epoch))
            except Exception:
                message_dt = None

        resolved = _complete_telegram_connection_for_start_message(
            db,
            token=token,
            chat_id=str(chat_id),
            message_dt=message_dt,
        )
        if resolved is not None:
            return resolved

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
    max_uv = max((h.uv_index or 0.0) for h in hours)

    today = now.date()
    sections: list[str] = []

    outfit = get_or_generate_outfit(db, location.id, today)
    wear_line = outfit.summary if outfit else _fallback_wear_tip(current_temp)
    umbrella_line = "Yes" if outfit and outfit.umbrella else ("Yes" if precip_total >= 4 else "No")
    shoes_line = outfit.shoes if outfit else _fallback_shoe_tip(precip_total, current_temp)
    sunscreen_line = outfit.sunscreen if outfit else _fallback_sunscreen_tip(max_uv)
    sections.append(
        _format_message_section(
            "What to Wear",
            [
                wear_line,
                f"Umbrella: {umbrella_line}",
                f"Shoes: {shoes_line}",
                f"Sunscreen: {sunscreen_line}",
            ],
        )
    )

    weather_entries = [
        f"Location: {location.name}",
        f"Now: {current_temp:.1f} C" if current_temp is not None else "Now: n/a",
        f"Next hour: {next_hour_temp:.1f} C" if next_hour_temp is not None else "Next hour: n/a",
        f"24h precipitation: {precip_total:.1f} mm",
        f"Max wind: {max_wind:.1f} kph",
        f"Max UV: {max_uv:.1f}",
    ]
    sections.append(_format_message_section("Detailed Forecast", weather_entries))

    if subscription.include_plan:
        plan_rows = get_plan_windows(db, location.id, today)
        if plan_rows:
            top = sorted(plan_rows, key=lambda row: row.score, reverse=True)[:2]
            sections.append(
                _format_message_section(
                    "Plan Windows",
                    [f"{row.category.title()}: around {row.best_hour:02d}:00 ({row.score:.0f}/100)" for row in top],
                )
            )

    if subscription.include_health:
        health = get_or_generate_health_alert(db, location.id, today)
        if health:
            sections.append(
                _format_message_section(
                    "Health Risks",
                    [
                        f"Heat: {health.heat_risk}/100",
                        f"Dehydration: {health.dehydration_risk}/100",
                        f"Asthma proxy: {health.asthma_proxy_risk}/100",
                    ],
                )
            )

    title = f"Forecast Hub Daily Brief · {location.name}"
    if severity == "high":
        title = f"Severe Weather Alert · {location.name}"
        if reason:
            sections.insert(1, _format_message_section("Alert", [f"High-risk condition detected: {reason}"]))

    body = "\n\n".join([section for section in sections if section])
    return {"title": title, "body": body}


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
    telegram_commands_processed = _process_telegram_settings_commands(db)
    scheduled = _enqueue_due_daily_jobs(db, now)
    escalations = _enqueue_severe_escalations(db, now)
    processed = _process_due_jobs(db, now)
    return {
        "telegram_commands_processed": telegram_commands_processed,
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
