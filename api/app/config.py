from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ForecastHub API"
    environment: str = "development"

    database_url: str = "sqlite:///./forecast_hub.db"
    supabase_database_url: str | None = None
    database_url_dev: str | None = None
    database_url_prod: str | None = None
    supabase_database_url_dev: str | None = None
    supabase_database_url_prod: str | None = None

    frontend_origin: str = "http://localhost:5173"
    frontend_origin_dev: str | None = None
    frontend_origin_prod: str | None = None

    default_location_name: str = "Chicago"
    default_location_latitude: float = 41.8781
    default_location_longitude: float = -87.6298
    default_location_timezone: str = "America/Chicago"

    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    request_timeout_seconds: int = 20
    open_meteo_cache_ttl_seconds: int = 900
    open_meteo_cache_stale_ttl_seconds: int = 21600

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    scheduler_job_token: str = "replace-me"

    mlflow_tracking_uri: str = "file:./mlruns"
    mlflow_experiment_name: str = "forecast_hub_temperature"
    mlflow_model_name: str = "forecast_hub_next_hour_temperature"

    model_min_training_rows: int = 200
    model_bootstrap_min_rows: int = 72
    model_training_max_rows: int = 5000
    model_promote_rmse_margin: float = 0.995
    model_rf_n_estimators: int = 30
    model_rf_min_samples_leaf: int = 2
    model_rf_max_depth: int | None = 10
    model_rf_n_jobs: int = 1

    notification_scheduler_enabled: bool = True
    notification_scheduler_interval_seconds: int = 60
    notification_job_batch_size: int = 20
    notification_max_retries: int = 3
    notification_retry_backoff_seconds: str = "60,300,900"
    notification_connect_token_ttl_minutes: int = 30

    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None

    forecasthub_api_base_url: str | None = None
    forecasthub_api_base_url_dev: str | None = None
    forecasthub_api_base_url_prod: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    discord_client_id: str | None = None
    discord_client_secret: str | None = None

    severe_risk_threshold: int = 70
    severe_precip_threshold_mm: float = 25.0
    severe_wind_threshold_kph: float = 50.0
    severe_escalation_cooldown_minutes: int = 240

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    def _pick_by_env(
        self,
        *,
        dev_value: str | None,
        prod_value: str | None,
        fallback: str | None,
    ) -> str:
        primary = prod_value if self.is_production else dev_value
        selected = (primary or "").strip() or (fallback or "").strip()
        return selected

    @property
    def runtime_frontend_origin(self) -> str:
        return self._pick_by_env(
            dev_value=self.frontend_origin_dev,
            prod_value=self.frontend_origin_prod,
            fallback=self.frontend_origin,
        )

    @property
    def runtime_forecasthub_api_base_url(self) -> str | None:
        value = self._pick_by_env(
            dev_value=self.forecasthub_api_base_url_dev,
            prod_value=self.forecasthub_api_base_url_prod,
            fallback=self.forecasthub_api_base_url,
        )
        return value or None

    @property
    def allowed_origins(self) -> list[str]:
        source = self.runtime_frontend_origin
        return [origin.strip() for origin in source.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        supabase_candidate = self._pick_by_env(
            dev_value=self.supabase_database_url_dev,
            prod_value=self.supabase_database_url_prod,
            fallback=self.supabase_database_url,
        )
        database_candidate = self._pick_by_env(
            dev_value=self.database_url_dev,
            prod_value=self.database_url_prod,
            fallback=self.database_url,
        )
        if supabase_candidate.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            raw_url = supabase_candidate
        else:
            raw_url = database_candidate
        url = raw_url.strip()
        if url.startswith("postgres://"):
            url = f"postgresql://{url.removeprefix('postgres://')}"
        if url.startswith("postgresql://"):
            return f"postgresql+psycopg://{url.removeprefix('postgresql://')}"
        return url

    @property
    def notification_retry_backoff(self) -> list[int]:
        values: list[int] = []
        for item in self.notification_retry_backoff_seconds.split(","):
            parsed = item.strip()
            if not parsed:
                continue
            try:
                values.append(max(1, int(parsed)))
            except ValueError:
                continue
        return values or [60, 300, 900]


settings = Settings()
