"""Video / asset request-response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AssetPublic(ORMModel):
    id: str
    project_id: str
    kind: str
    filename: str
    content_type: str
    public_id: str
    secure_url: str
    resource_type: str
    format: str | None
    width: int | None
    height: int | None
    duration: float | None
    size: int
    created_at: datetime
    updated_at: datetime


class VideoPublic(ORMModel):
    id: str
    project_id: str
    status: str
    thumbnail_url: str | None
    original_asset: AssetPublic
    post_process_job_id: str | None = None
    created_at: datetime
    updated_at: datetime


class VideoListItem(ORMModel):
    id: str
    project_id: str
    status: str
    thumbnail_url: str | None
    filename: str
    duration: float | None
    width: int | None
    height: int | None
    size: int
    created_at: datetime
    updated_at: datetime


class VideoUploadMeta(BaseModel):
    """Optional form fields alongside multipart file."""

    filename: str | None = Field(default=None, max_length=512)
