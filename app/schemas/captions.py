"""Captions request/response schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

CaptionStyle = Literal["minimal", "dynamic"]


class CaptionWord(BaseModel):
    word: str
    start: float
    end: float


class CaptionCue(BaseModel):
    id: str
    start: float
    end: float
    text: str
    words: list[CaptionWord] = Field(default_factory=list)


class CaptionsPublic(ORMModel):
    id: str
    video_id: str
    job_id: str | None
    status: str
    style: str
    language: str | None
    cues: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class CaptionsGenerateRequest(BaseModel):
    style: CaptionStyle | None = None


class CaptionsStarted(BaseModel):
    captions_id: str
    job_id: str
    status: str


class CaptionsPatchRequest(BaseModel):
    style: CaptionStyle | None = None
    cues: list[CaptionCue] | None = None
