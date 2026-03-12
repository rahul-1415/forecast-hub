from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class LocationRead(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    timezone: str


class LocationSuggestion(BaseModel):
    name: str
    label: str


class OverviewStats(BaseModel):
    min_temp_c: float | None
    max_temp_c: float | None
    precipitation_total_mm: float | None
    avg_wind_kph: float | None


class HourlyTemperaturePoint(BaseModel):
    timestamp: datetime
    temperature_c: float | None


class HourlyTemperatureBandPoint(BaseModel):
    timestamp: datetime
    temperature_c: float | None
    lower_c: float | None
    upper_c: float | None


class SourceComparison(BaseModel):
    open_meteo_next_hour_c: float | None = None
    custom_ml_next_hour_c: float | None = None
    delta_c: float | None = None
    rmse_c: float | None = None
    preferred_source: Literal["open_meteo", "custom_ml", "mixed"] = "mixed"
    confidence_note: str


class RecommendationDetail(BaseModel):
    recommendation: str
    why: str
    source: str


class WeeklySummary(BaseModel):
    window_start: date
    window_end: date
    average_temp_c: float | None = None
    average_temp_delta_vs_prev_week_c: float | None = None
    total_precipitation_mm: float | None = None
    precipitation_delta_vs_prev_week_mm: float | None = None
    anomalies_last_7d: int = 0
    anomalies_delta_vs_prev_week: int | None = None
    best_windows: list[str] = []
    insights: list[str] = []


class OverviewResponse(BaseModel):
    location: LocationRead
    generated_at: datetime
    current_temperature_c: float | None = None
    next_hour_temperature_open_meteo_c: float | None = None
    next_hour_temperature_custom_model_c: float | None = None
    next_24h: OverviewStats
    top_recommendations: list[str]
    alert_level: str
    anomalies_last_7d: int
    next_hour_temperature_prediction_c: float | None = None
    hourly_temperatures_24h: list[HourlyTemperaturePoint] = []
    hourly_temperatures_24h_custom_model: list[HourlyTemperaturePoint] = []
    hourly_temperatures_24h_custom_model_bands: list[HourlyTemperatureBandPoint] = []
    custom_model_rmse_c: float | None = None
    source_comparison_next_hour: SourceComparison | None = None
    recommendation_details: list[RecommendationDetail] = []
    weekly_summary: WeeklySummary | None = None
    data_freshness: str = "fresh"
    stale_reason: str | None = None


class PlanWindowItem(BaseModel):
    category: str
    best_hour: int
    score: float
    summary: str


class PlanResponse(BaseModel):
    location: LocationRead
    target_date: date
    windows: list[PlanWindowItem]


class OutfitResponse(BaseModel):
    location: LocationRead
    target_date: date
    summary: str
    umbrella: bool
    layer_level: str
    shoes: str
    sunscreen: str
    hydration_liters: float


class HealthResponse(BaseModel):
    location: LocationRead
    target_date: date
    heat_risk: int
    cold_risk: int
    dehydration_risk: int
    sleep_comfort_index: int
    asthma_proxy_risk: int
    summary: str


class AnomalyItem(BaseModel):
    detected_at: datetime
    metric: str
    anomaly_type: str
    severity: str
    expected_value: float | None
    observed_value: float | None
    z_score: float | None
    summary: str


class AnomaliesResponse(BaseModel):
    location: LocationRead
    window_days: int
    items: list[AnomalyItem]


class JobRunResponse(BaseModel):
    status: str
    processed_locations: int
    ingested_rows: int
    generated_plan_rows: int
    generated_anomalies: int
    message: str


class ModelTrainResponse(BaseModel):
    status: str
    version_id: int
    run_id: str
    model_uri: str
    metrics: dict
    promoted: bool
    message: str


class ModelVersionItem(BaseModel):
    id: int
    model_name: str
    run_id: str
    model_uri: str
    status: str
    metrics: dict | None
    created_at: datetime
    promoted_at: datetime | None


class ModelVersionsResponse(BaseModel):
    items: list[ModelVersionItem]


class NotificationSubscriptionCreate(BaseModel):
    location_name: str
    channel: Literal["telegram", "discord", "slack"]
    destination: str
    enabled: bool = True
    schedule_time: str = "08:00"
    timezone: str = "UTC"
    include_outfit: bool = True
    include_health: bool = True
    include_plan: bool = True
    quiet_hours_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    escalation_enabled: bool = True


class NotificationSubscriptionUpdate(BaseModel):
    location_name: str | None = None
    enabled: bool | None = None
    schedule_time: str | None = None
    timezone: str | None = None
    include_outfit: bool | None = None
    include_health: bool | None = None
    include_plan: bool | None = None
    quiet_hours_enabled: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    escalation_enabled: bool | None = None


class NotificationSubscriptionItem(BaseModel):
    id: int
    location_name: str
    channel: str
    destination: str
    enabled: bool
    schedule_time: str
    timezone: str
    include_outfit: bool
    include_health: bool
    include_plan: bool
    quiet_hours_enabled: bool
    quiet_start: str
    quiet_end: str
    escalation_enabled: bool
    next_run_at: datetime | None
    last_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationSubscriptionsResponse(BaseModel):
    items: list[NotificationSubscriptionItem]


class NotificationSendTestRequest(BaseModel):
    subscription_id: int
    force_severity: Literal["normal", "high"] = "normal"


class NotificationSendTestResponse(BaseModel):
    status: str
    job_id: int
    message: str


class NotificationDeliveryLogItem(BaseModel):
    id: int
    job_id: int
    subscription_id: int
    channel: str
    destination: str
    status: str
    attempt_number: int
    response_code: int | None
    provider_message: str | None
    payload: dict | None
    created_at: datetime


class NotificationDeliveryLogsResponse(BaseModel):
    items: list[NotificationDeliveryLogItem]


class NotificationConnectStartRequest(BaseModel):
    location_name: str
    channel: Literal["telegram", "discord", "slack"]
    enabled: bool = True
    schedule_time: str = "08:00"
    timezone: str = "UTC"
    include_outfit: bool = True
    include_health: bool = True
    include_plan: bool = True
    quiet_hours_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    escalation_enabled: bool = True


class NotificationConnectStartResponse(BaseModel):
    token: str
    channel: Literal["telegram", "discord", "slack"]
    connect_url: str
    expires_at: datetime
    instructions: str


class NotificationConnectStatusResponse(BaseModel):
    token: str
    channel: Literal["telegram", "discord", "slack"]
    status: Literal["pending", "connected", "failed", "expired"]
    subscription_id: int | None
    destination: str | None
    error_message: str | None


class NotificationTelegramConnectCompleteRequest(BaseModel):
    token: str
