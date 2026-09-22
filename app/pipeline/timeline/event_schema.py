"""Shared montage event timeline — single source of truth for timed decisions.

All modules emit scored / typed events into this document. Downstream placement
(budget, cooldown, render) consumes it; modules must not invent parallel clocks.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


Clock = Literal["source"]
SfxCategory = Literal["chime", "pop", "whoosh", "riser", "swipe"]
ZoomKind = Literal["zoom_in_tight", "zoom_in_soft", "zoom_out", "micro_pan"]
EmphasisKind = Literal["keyword", "number", "negation", "proper"]
TransitionKind = Literal["cut", "whoosh", "dissolve"]


class EventBase(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    important: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class WordEvent(EventBase):
    type: Literal["word"] = "word"
    text: str
    speaker: str | None = None
    emphasis: EmphasisKind | None = None


class KeepEvent(EventBase):
    type: Literal["keep"] = "keep"


class CutEvent(EventBase):
    type: Literal["cut"] = "cut"
    reason: str | None = None


class OverlayEvent(EventBase):
    type: Literal["overlay"] = "overlay"
    overlay_id: str
    layout: str = "plate"
    prompt: str | None = None


class ZoomEvent(EventBase):
    type: Literal["zoom"] = "zoom"
    kind: ZoomKind = "zoom_in_soft"
    scale: float = Field(default=1.15, gt=1.0, le=3.0)
    focus_x: float = Field(default=0.5, ge=0.0, le=1.0)
    focus_y: float = Field(default=0.5, ge=0.0, le=1.0)


class TransitionEvent(EventBase):
    type: Literal["transition"] = "transition"
    kind: TransitionKind = "cut"


class SfxEvent(EventBase):
    type: Literal["sfx"] = "sfx"
    category: SfxCategory
    asset_id: str | None = None
    volume_db: float = Field(default=-12.0, le=0.0)


class BeatEvent(EventBase):
    type: Literal["beat"] = "beat"


TimelineEvent = Annotated[
    WordEvent
    | KeepEvent
    | CutEvent
    | OverlayEvent
    | ZoomEvent
    | TransitionEvent
    | SfxEvent
    | BeatEvent,
    Field(discriminator="type"),
]


class EventTimeline(BaseModel):
    schema_version: str = "1.0.0"
    clock: Clock = "source"
    video_id: str
    duration: float = Field(ge=0)
    needs_review: bool = False
    dry_run: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    events: list[TimelineEvent] = Field(default_factory=list)

    def of_type(self, event_type: str) -> list[TimelineEvent]:
        return [e for e in self.events if e.type == event_type]
