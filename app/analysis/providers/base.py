"""Transcription provider protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class TranscriptWordResult:
    word: str
    start: float
    end: float


@dataclass(slots=True)
class TranscriptSegmentResult:
    id: str
    start: float
    end: float
    text: str
    words: list[TranscriptWordResult] = field(default_factory=list)


@dataclass(slots=True)
class TranscriptResult:
    language: str
    segments: list[TranscriptSegmentResult]
    vad_segments: list[dict] = field(default_factory=list)
    fillers: list[dict] = field(default_factory=list)
    quality_warning: str | None = None
    aligned: bool = False


class TranscriptionProvider(Protocol):
    def transcribe(
        self,
        *,
        duration: float,
        language: str | None = None,
        media_url: str | None = None,
    ) -> TranscriptResult: ...
