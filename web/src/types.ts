export type LocationRead = {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  timezone: string;
};

export type LocationSuggestion = {
  name: string;
  label: string;
};

export type OverviewResponse = {
  location: LocationRead;
  generated_at: string;
  current_temperature_c?: number | null;
  next_hour_temperature_open_meteo_c?: number | null;
  next_hour_temperature_custom_model_c?: number | null;
  next_24h: {
    min_temp_c: number | null;
    max_temp_c: number | null;
    precipitation_total_mm: number | null;
    avg_wind_kph: number | null;
  };
  top_recommendations: string[];
  alert_level: string;
  anomalies_last_7d: number;
  next_hour_temperature_prediction_c?: number | null;
  hourly_temperatures_24h?: {
    timestamp: string;
    temperature_c: number | null;
  }[];
  hourly_temperatures_24h_custom_model?: {
    timestamp: string;
    temperature_c: number | null;
  }[];
  hourly_temperatures_24h_custom_model_bands?: {
    timestamp: string;
    temperature_c: number | null;
    lower_c: number | null;
    upper_c: number | null;
  }[];
  custom_model_rmse_c?: number | null;
  source_comparison_next_hour?: {
    open_meteo_next_hour_c: number | null;
    custom_ml_next_hour_c: number | null;
    delta_c: number | null;
    rmse_c: number | null;
    preferred_source: "open_meteo" | "custom_ml" | "mixed";
    confidence_note: string;
  } | null;
  recommendation_details?: {
    recommendation: string;
    why: string;
    source: string;
  }[];
  weekly_summary?: {
    window_start: string;
    window_end: string;
    average_temp_c: number | null;
    average_temp_delta_vs_prev_week_c: number | null;
    total_precipitation_mm: number | null;
    precipitation_delta_vs_prev_week_mm: number | null;
    anomalies_last_7d: number;
    anomalies_delta_vs_prev_week: number | null;
    best_windows: string[];
    insights: string[];
  } | null;
  data_freshness?: string;
  stale_reason?: string | null;
};

export type PlanWindowItem = {
  category: string;
  best_hour: number;
  score: number;
  summary: string;
};

export type PlanResponse = {
  location: LocationRead;
  target_date: string;
  windows: PlanWindowItem[];
};

export type OutfitResponse = {
  location: LocationRead;
  target_date: string;
  summary: string;
  umbrella: boolean;
  layer_level: string;
  shoes: string;
  sunscreen: string;
  hydration_liters: number;
};

export type HealthResponse = {
  location: LocationRead;
  target_date: string;
  heat_risk: number;
  cold_risk: number;
  dehydration_risk: number;
  sleep_comfort_index: number;
  asthma_proxy_risk: number;
  summary: string;
};

export type AnomalyItem = {
  detected_at: string;
  metric: string;
  anomaly_type: string;
  severity: "low" | "medium" | "high";
  expected_value: number | null;
  observed_value: number | null;
  z_score: number | null;
  summary: string;
};

export type AnomaliesResponse = {
  location: LocationRead;
  window_days: number;
  items: AnomalyItem[];
};

export type NotificationSubscription = {
  id: number;
  location_name: string;
  channel: "telegram" | "discord" | "slack";
  destination: string;
  enabled: boolean;
  schedule_time: string;
  timezone: string;
  include_outfit: boolean;
  include_health: boolean;
  include_plan: boolean;
  quiet_hours_enabled: boolean;
  quiet_start: string;
  quiet_end: string;
  escalation_enabled: boolean;
  next_run_at: string | null;
  last_sent_at: string | null;
  created_at: string;
  updated_at: string;
};

export type NotificationChannel = "telegram" | "discord" | "slack";

export type NotificationConnectStartResponse = {
  token: string;
  channel: NotificationChannel;
  connect_url: string;
  expires_at: string;
  instructions: string;
};

export type NotificationConnectStatusResponse = {
  token: string;
  channel: NotificationChannel;
  status: "pending" | "connected" | "failed" | "expired";
  subscription_id: number | null;
  destination: string | null;
  error_message: string | null;
};

export type NotificationDeliveryLog = {
  id: number;
  job_id: number;
  subscription_id: number;
  channel: string;
  destination: string;
  status: string;
  attempt_number: number;
  response_code: number | null;
  provider_message: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
};
