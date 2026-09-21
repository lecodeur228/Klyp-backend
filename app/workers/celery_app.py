"""Celery application."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "fastapi_ai_starter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks.ai", "app.workers.tasks.files", "app.workers.tasks.cleanup"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.workers.tasks.ai.*": {"queue": "ai"},
        "app.workers.tasks.files.*": {"queue": "files"},
        "app.workers.tasks.cleanup.*": {"queue": "default"},
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
