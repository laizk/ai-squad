from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI Squad Control API")
    app_version: str = os.getenv("APP_VERSION", "0.2.0-foundation")
    app_env: str = os.getenv("APP_ENV", "development")
    app_phase: str = os.getenv("APP_PHASE", "P0")
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "")
    health_timeout_seconds: float = float(os.getenv("HEALTH_TIMEOUT_SECONDS", "2.0"))


settings = Settings()
