"""Analysis request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float


class TranscriptSegment(BaseModel):
    id: str
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class VadSegment(BaseModel):
    start: float
    end: float
    kind: str = "silence"


class FillerHit(BaseModel):
    word: str
    start: float
    end: float


class AnalysisPublic(ORMModel):
    id: str
    video_id: str
    job_id: str | None
    status: str
    language: str | None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    vad_segments: list[dict[str, Any]] = Field(default_factory=list)
    fillers: list[dict[str, Any]] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    faces: list[dict[str, Any]] = Field(default_factory=list)
    quality_warning: str | None = None
    aligned: bool = False
    needs_review: bool = False
    qa_metrics: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisStarted(BaseModel):
    analysis_id: str
    job_id: str
    status: str
