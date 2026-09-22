"""Render request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import ORMModel

RenderKind = Literal["preview", "export"]


class RenderRequest(BaseModel):
    kind: RenderKind = "export"


class RenderStarted(BaseModel):
    render_id: str
    job_id: str
    status: str


class RenderPublic(ORMModel):
    id: str
    project_id: str
    user_id: str
    edit_plan_id: str
    source_video_id: str
    job_id: str | None
    output_asset_id: str | None
    status: str
    kind: str
    secure_url: str | None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
