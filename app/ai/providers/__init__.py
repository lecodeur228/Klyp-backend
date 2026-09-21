"""Provider factory."""

from functools import lru_cache

from app.ai.providers.base import AIProvider
from app.ai.providers.fake import FakeAIProvider
from app.ai.providers.rodiumai import RodiumAIProvider
from app.core.config import Settings, get_settings


def build_provider(settings: Settings | None = None) -> AIProvider:
    cfg = settings or get_settings()
    if cfg.ai_provider == "rodiumai" and cfg.rodiumai_api_key:
        return RodiumAIProvider(cfg)
    if cfg.ai_provider == "rodiumai" and cfg.is_production:
        raise RuntimeError("RODIUMAI_API_KEY is required in production")
    return FakeAIProvider()


@lru_cache
def get_ai_provider() -> AIProvider:
    return build_provider()
