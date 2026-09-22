"""Job request/response schemas."""

from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class JobPublic(ORMModel):
    id: str
    type: str
    status: str
    progress: int
    stage: str | None
    user_id: str
    project_id: str | None
    video_id: str | None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobProgressEvent(ORMModel):
    """Lightweight WS / poll snapshot."""

    id: str
    status: str
    progress: int
    stage: str | None
    error_code: str | None = None
