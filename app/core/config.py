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

    app_name: str = "Klyp"
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
    rodiumai_plan_model: str = "openai/gpt-4o"
    rodiumai_embedding_model: str = "openai/text-embedding-3-small"
    rodiumai_timeout: float = 60.0
    rodiumai_max_retries: int = 2

    # Quotas / rate limits (basic V1)
    ai_rate_limit_per_minute: int = 30
    ai_daily_token_quota: int = 100_000

    # Storage
    storage_backend: Literal["local", "cloudinary", "s3"] = "local"
    storage_local_path: str = "storage/uploads"
    storage_max_upload_mb: int = 10
    video_max_upload_mb: int = 500
    # Transcription (ASR) — whisperx | rodiumai | fake | auto
    transcription_provider: Literal["fake", "rodiumai", "whisperx", "auto"] = "auto"
    transcription_model: str = "openai/gpt-4o-transcribe-diarize"
    whisperx_model: str = "base"
    image_model: str = "openai/gpt-image-2"
    image_timeout: float = 180.0
    # Cloudinary (source de vérité média au lancement)
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    # S3 stub (non utilisé au lancement — PRD)
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Credits pricing (integers)
    credits_analyze_base: int = 5
    credits_analyze_per_min: int = 2
    credits_ai_edit_base: int = 15
    credits_ai_edit_per_min: int = 5
    credits_render_base: int = 20
    credits_render_per_min: int = 8
    credits_render_preview_factor: float = 0.5
    payment_provider: Literal["stub"] = "stub"

    # Monitoring
    sentry_dsn: str = ""

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

    @property
    def cloudinary_configured(self) -> bool:
        return bool(
            self.cloudinary_cloud_name
            and self.cloudinary_api_key
            and self.cloudinary_api_secret
        )

    @property
    def rodiumai_configured(self) -> bool:
        return bool(self.rodiumai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
