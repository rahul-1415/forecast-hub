from datetime import date, datetime

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
