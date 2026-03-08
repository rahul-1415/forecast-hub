from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ForecastHub API"
    environment: str = "development"

    database_url: str = "sqlite:///./forecast_hub.db"

    frontend_origin: str = "http://localhost:5173"

    default_location_name: str = "Chicago"
    default_location_latitude: float = 41.8781
    default_location_longitude: float = -87.6298
    default_location_timezone: str = "America/Chicago"

    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    request_timeout_seconds: int = 20

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    scheduler_job_token: str = "replace-me"

    mlflow_tracking_uri: str = "file:./mlruns"
    mlflow_experiment_name: str = "forecast_hub_temperature"
    mlflow_model_name: str = "forecast_hub_next_hour_temperature"

    model_min_training_rows: int = 200
    model_promote_rmse_margin: float = 0.995

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = f"postgresql://{url.removeprefix('postgres://')}"
        if url.startswith("postgresql://"):
            return f"postgresql+psycopg://{url.removeprefix('postgresql://')}"
        return url


settings = Settings()
