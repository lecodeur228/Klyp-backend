"""Cleanup tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.cleanup.purge_expired_tokens")
def purge_expired_tokens() -> dict[str, str]:
    return {"status": "ok"}
