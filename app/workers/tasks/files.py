"""File processing tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.files.process_file")
def process_file(file_path: str) -> dict[str, str]:
    return {"status": "processed", "path": file_path}
