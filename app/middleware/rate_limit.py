"""Simple Redis-backed rate limiting middleware for AI routes."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.constants import ErrorCode


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory fallback rate limiter (per-process). Redis used when available."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._buckets: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not request.url.path.startswith(f"{settings.api_v1_prefix}/ai"):
            return await call_next(request)

        identity = (
            request.headers.get("authorization")
            or request.headers.get("x-api-key")
            or (request.client.host if request.client else "anon")
        )
        key = f"{identity}:{request.url.path}"
        now = time.time()
        window = 60.0
        limit = settings.ai_rate_limit_per_minute
        hits = [t for t in self._buckets.get(key, []) if now - t < window]
        if len(hits) >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "message": "Rate limit exceeded",
                    "code": ErrorCode.RATE_LIMIT_EXCEEDED.value,
                },
            )
        hits.append(now)
        self._buckets[key] = hits
        return await call_next(request)
