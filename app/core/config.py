"""Application settings — fail fast on invalid configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "FastAPI AI Starter"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str = Field(
        default="change-me-to-a-long-random-secret-key-at-least-32",
        min_length=32,
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fastapi_ai"
    database_url_sync: str = "postgresql+psycopg://postgres:postgres@localhost:5432/fastapi_ai"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Auth
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    jwt_algorithm: str = "HS256"

    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # AI
    ai_provider: Literal["rodiumai", "fake"] = "fake"
    rodiumai_api_key: str = ""
    rodiumai_base_url: str = "https://api.rodiumai.io/v1"
    rodiumai_default_model: str = "openai/gpt-4o-mini"
    rodiumai_embedding_model: str = "openai/text-embedding-3-small"
    rodiumai_timeout: float = 60.0
    rodiumai_max_retries: int = 2

    # Quotas / rate limits (basic V1)
    ai_rate_limit_per_minute: int = 30
    ai_daily_token_quota: int = 100_000

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "storage/uploads"
    storage_max_upload_mb: int = 10
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # i18n
    default_locale: Literal["fr", "en"] = "fr"
    supported_locales: list[str] = Field(default_factory=lambda: ["fr", "en"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip() == "*":
                return ["*"]
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
