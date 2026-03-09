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
