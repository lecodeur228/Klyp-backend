"""Project request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ProjectPublic(ORMModel):
    id: str
    user_id: str
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    latest_video_id: str | None = None
    thumbnail_url: str | None = None
