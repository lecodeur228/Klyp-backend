"""Health routes."""

from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import AppSettings, DbSession, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: DbSession, settings: AppSettings, locale: LocaleDep):
    checks: dict[str, str] = {"database": "ok", "redis": "ok", "queue": "ok"}
    status = "ok"
    http_status = 200

    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "unhealthy"
        status = "unhealthy"
        http_status = 503

    try:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url)
        await client.ping()
        await client.close()
    except Exception:
        checks["redis"] = "degraded"
        checks["queue"] = "degraded"
        if status == "ok":
            status = "degraded"

    message_key = {
        "ok": "health_ok",
        "degraded": "health_degraded",
        "unhealthy": "health_unhealthy",
    }[status]

    return success_response(
        {"status": status, "checks": checks},
        translate(message_key, locale),
        status_code=http_status,
    )
