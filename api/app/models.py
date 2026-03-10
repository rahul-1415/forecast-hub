from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class HourlyWeather(Base):
    __tablename__ = "hourly_weather"
    __table_args__ = (UniqueConstraint("location_id", "timestamp", name="uq_hourly_weather_location_timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)

    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    apparent_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    rain_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_kph: Mapped[float | None] = mapped_column(Float, nullable=True)
    uv_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure_hpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_day: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class PlanWindow(Base):
    __tablename__ = "plan_windows"
    __table_args__ = (UniqueConstraint("location_id", "target_date", "category", name="uq_plan_window_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    best_hour: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class OutfitRecommendation(Base):
    __tablename__ = "outfit_recommendations"
    __table_args__ = (UniqueConstraint("location_id", "target_date", name="uq_outfit_recommendation_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)

    summary: Mapped[str] = mapped_column(Text)
    umbrella: Mapped[bool] = mapped_column(Boolean, default=False)
    layer_level: Mapped[str] = mapped_column(String(32))
    shoes: Mapped[str] = mapped_column(String(64))
    sunscreen: Mapped[str] = mapped_column(String(64))
    hydration_liters: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class HealthAlert(Base):
    __tablename__ = "health_alerts"
    __table_args__ = (UniqueConstraint("location_id", "target_date", name="uq_health_alert_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)

    heat_risk: Mapped[int] = mapped_column(Integer)
    cold_risk: Mapped[int] = mapped_column(Integer)
    dehydration_risk: Mapped[int] = mapped_column(Integer)
    sleep_comfort_index: Mapped[int] = mapped_column(Integer)
    asthma_proxy_risk: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "detected_at",
            "metric",
            "anomaly_type",
            name="uq_anomaly_event_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    anomaly_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_name: Mapped[str] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("run_id", name="uq_model_version_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    model_name: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    model_uri: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feature_columns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    __table_args__ = (UniqueConstraint("model_version_id", name="uq_model_artifact_model_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_format: Mapped[str] = mapped_column(String(32), default="joblib")
    artifact_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        UniqueConstraint("channel", "destination", "location_name", name="uq_notification_subscription_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_name: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(24), index=True)
    destination: Mapped[str] = mapped_column(String(255), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    schedule_time: Mapped[str] = mapped_column(String(5), default="08:00")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    include_outfit: Mapped[bool] = mapped_column(Boolean, default=True)
    include_health: Mapped[bool] = mapped_column(Boolean, default=True)
    include_plan: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="07:00")
    escalation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
    )


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    __table_args__ = (
        UniqueConstraint("subscription_id", "dedupe_key", name="uq_notification_job_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("notification_subscriptions.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="normal", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
    )


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("notification_jobs.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("notification_subscriptions.id", ondelete="CASCADE"),
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(24), index=True)
    destination: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class SevereWeatherEvent(Base):
    __tablename__ = "severe_weather_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), index=True)
