"""Build / enrich the shared event timeline from analysis + EditPlan."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from app.pipeline.timeline.event_schema import (
    CutEvent,
    EventTimeline,
    KeepEvent,
    OverlayEvent,
    WordEvent,
    ZoomEvent,
)
from app.schemas.editplan import EditPlanDocument

_NEGATIONS = frozenset(
    {
        "pas",
        "non",
        "jamais",
        "rien",
        "aucun",
        "aucune",
        "plus",
        "sans",
        "not",
        "never",
        "no",
        "none",
        "don't",
        "doesn't",
        "won't",
        "can't",
    }
)
_KEYWORD_HINTS = frozenset(
    {
        "important",
        "clé",
        "secret",
        "astuce",
        "attention",
        "warning",
        "must",
        "always",
        "never",
        "best",
        "top",
        "pro",
        "gratuit",
        "free",
        "money",
        "argent",
    }
)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def classify_emphasis(word: str) -> str | None:
    raw = word.strip()
    if not raw:
        return None
    clean = re.sub(r"[^\w%-]", "", raw, flags=re.UNICODE)
    if not clean:
        return None
    if re.search(r"\d", clean):
        return "number"
    if clean.isupper() and len(clean) >= 2:
        return "proper"
    low = clean.lower()
    if low in _NEGATIONS:
        return "negation"
    if low in _KEYWORD_HINTS:
        return "keyword"
    return None


def words_from_analysis_segments(segments: list[dict[str, Any]] | None) -> list[WordEvent]:
    out: list[WordEvent] = []
    for seg in segments or []:
        words = seg.get("words") or []
        if not words and seg.get("text"):
            # Fallback: whole segment as one word span
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or start)
            text = str(seg.get("text") or "").strip()
            if text:
                emph = classify_emphasis(text.split()[0] if text.split() else text)
                out.append(
                    WordEvent(
                        id=_new_id("w"),
                        start=start,
                        end=max(end, start),
                        text=text,
                        emphasis=emph,  # type: ignore[arg-type]
                        important=emph is not None,
                        score=0.9 if emph else 0.5,
                    )
                )
            continue
        for w in words:
            text = str(w.get("word") or w.get("text") or "").strip()
            if not text:
                continue
            start = float(w.get("start") or 0)
            end = float(w.get("end") or start)
            emph = classify_emphasis(text)
            out.append(
                WordEvent(
                    id=_new_id("w"),
                    start=start,
                    end=max(end, start),
                    text=text,
                    speaker=w.get("speaker"),
                    emphasis=emph,  # type: ignore[arg-type]
                    important=emph is not None,
                    score=0.95 if emph else 0.55,
                )
            )
    return out


def build_event_timeline(
    *,
    video_id: str,
    duration: float,
    plan: EditPlanDocument,
    analysis_segments: list[dict[str, Any]] | None = None,
    needs_review: bool = False,
    dry_run: bool = False,
    metrics: dict[str, Any] | None = None,
) -> EventTimeline:
    events: list = []

    for seg in plan.timeline.segments:
        events.append(
            KeepEvent(
                id=seg.id or _new_id("keep"),
                start=float(seg.start),
                end=float(seg.end),
                score=1.0,
            )
        )

    # Derive cut gaps between keep segments (source clock)
    keeps = sorted(plan.timeline.segments, key=lambda s: s.start)
    for i in range(len(keeps) - 1):
        gap_start = float(keeps[i].end)
        gap_end = float(keeps[i + 1].start)
        if gap_end - gap_start > 0.05:
            events.append(
                CutEvent(
                    id=_new_id("cut"),
                    start=gap_start,
                    end=gap_end,
                    reason="keep_gap",
                    score=0.8,
                )
            )

    events.extend(words_from_analysis_segments(analysis_segments))

    for ov in plan.overlays:
        events.append(
            OverlayEvent(
                id=_new_id("ov"),
                start=float(ov.start),
                end=float(ov.end),
                overlay_id=ov.id,
                layout=ov.layout,
                prompt=ov.prompt,
                score=0.7,
                important=ov.layout in {"plate", "cover"},
            )
        )

    for op in plan.operations:
        if getattr(op, "type", None) == "zoom":
            events.append(
                ZoomEvent(
                    id=_new_id("zoom"),
                    start=float(op.start),
                    end=float(op.end),
                    scale=float(op.scale),
                    score=0.8,
                    important=True,
                )
            )

    events.sort(key=lambda e: (e.start, e.end, e.type))

    return EventTimeline(
        video_id=video_id,
        duration=max(duration, 0.0),
        needs_review=needs_review,
        dry_run=dry_run,
        metrics=metrics or {},
        events=events,
    )


def sync_plan_events(
    plan: EditPlanDocument,
    timeline: EventTimeline,
) -> EditPlanDocument:
    """Attach timeline JSON onto EditPlan (schema 1.5+)."""
    data = plan.model_dump()
    data["schema_version"] = "1.5.0"
    data["events"] = timeline.model_dump()
    return EditPlanDocument.model_validate(data)
