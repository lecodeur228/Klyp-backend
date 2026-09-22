"""Credits pricing formulas (integer credits)."""

from __future__ import annotations

import math
from typing import Any, Literal

from app.core.config import Settings

Operation = Literal["video.analyze", "ai_edit", "project.render"]
RenderKind = Literal["preview", "export"]


def duration_minutes(duration_seconds: float | None) -> int:
    """Ceil duration to whole minutes; minimum 1 when duration unknown/zero."""
    if duration_seconds is None or duration_seconds <= 0:
        return 1
    return max(1, math.ceil(duration_seconds / 60.0))


def estimate_analyze(
    settings: Settings, *, duration_seconds: float | None
) -> tuple[int, dict[str, Any]]:
    mins = duration_minutes(duration_seconds)
    base = settings.credits_analyze_base
    per_min = settings.credits_analyze_per_min
    credits = base + mins * per_min
    return credits, {
        "operation": "video.analyze",
        "base": base,
        "per_min": per_min,
        "minutes": mins,
        "credits": credits,
    }


def estimate_ai_edit(
    settings: Settings, *, duration_seconds: float | None
) -> tuple[int, dict[str, Any]]:
    mins = duration_minutes(duration_seconds)
    base = settings.credits_ai_edit_base
    per_min = settings.credits_ai_edit_per_min
    credits = base + mins * per_min
    return credits, {
        "operation": "ai_edit",
        "base": base,
        "per_min": per_min,
        "minutes": mins,
        "credits": credits,
    }


def estimate_render(
    settings: Settings,
    *,
    duration_seconds: float | None,
    kind: RenderKind = "export",
) -> tuple[int, dict[str, Any]]:
    mins = duration_minutes(duration_seconds)
    base = settings.credits_render_base
    per_min = settings.credits_render_per_min
    raw = base + mins * per_min
    factor = settings.credits_render_preview_factor if kind == "preview" else 1.0
    credits = max(1, math.ceil(raw * factor))
    return credits, {
        "operation": "project.render",
        "kind": kind,
        "base": base,
        "per_min": per_min,
        "minutes": mins,
        "factor": factor,
        "credits": credits,
    }
