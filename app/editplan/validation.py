"""Business rules for EditPlan validation."""

from __future__ import annotations

import logging

from app.core.exceptions import EditPlanInvalidException
from app.schemas.editplan import (
    CropOperation,
    EditPlanDocument,
    OutputConfig,
    Timeline,
    TimelineSegment,
    ZoomOperation,
)

logger = logging.getLogger(__name__)

SUPPORTED_ASPECT_RATIOS = frozenset({"9:16", "16:9", "1:1", "4:5"})
SUPPORTED_RESOLUTIONS = frozenset({"720p", "1080p"})
SUPPORTED_OPS = frozenset({"zoom", "crop"})


def repair_edit_plan(plan: EditPlanDocument, *, duration: float) -> EditPlanDocument:
    """Clamp / normalize a noisy AI EditPlan so validation can succeed."""
    total = duration if duration and duration > 0 else 30.0

    keeps: list[tuple[float, float]] = []
    for seg in sorted(plan.timeline.segments, key=lambda s: s.start):
        start = max(0.0, min(float(seg.start), total))
        end = max(0.0, min(float(seg.end), total))
        if end <= start + 0.05:
            continue
        if keeps and start < keeps[-1][1] - 1e-6:
            start = keeps[-1][1]
            if end <= start + 0.05:
                continue
        keeps.append((start, end))
    if not keeps:
        keeps = [(0.0, total)]

    segments = [
        TimelineSegment(id=f"keep-{i + 1}", start=round(a, 3), end=round(b, 3))
        for i, (a, b) in enumerate(keeps)
        if b > a
    ]

    operations: list[ZoomOperation | CropOperation] = []
    for op in plan.operations:
        op_type = getattr(op, "type", None)
        if op_type == "crop":
            aspect = (
                op.aspect_ratio
                if op.aspect_ratio in SUPPORTED_ASPECT_RATIOS
                else "9:16"
            )
            mode = op.mode if op.mode in {"smart", "center"} else "smart"
            operations.append(CropOperation(aspect_ratio=aspect, mode=mode))
        elif op_type == "zoom":
            start = max(0.0, min(float(op.start), total))
            end = max(0.0, min(float(op.end), total))
            scale = float(op.scale)
            if end <= start + 0.05:
                continue
            if scale <= 1.0:
                scale = 1.15
            if scale > 5.0:
                scale = 5.0
            operations.append(
                ZoomOperation(
                    start=round(start, 3),
                    end=round(end, 3),
                    scale=round(scale, 3),
                )
            )

    aspect = (
        plan.output.aspect_ratio
        if plan.output.aspect_ratio in SUPPORTED_ASPECT_RATIOS
        else "9:16"
    )
    resolution = (
        plan.output.resolution
        if plan.output.resolution in SUPPORTED_RESOLUTIONS
        else "720p"
    )

    # Drop overlays that would break duration rules; keep the rest as-is when valid
    overlays = []
    for ov in plan.overlays:
        try:
            start = max(0.0, min(float(ov.start), total))
            end = max(0.0, min(float(ov.end), total))
            if end <= start + 0.05:
                continue
            prompt = (ov.prompt or "illustration").strip()[:500] or "illustration"
            overlays.append(
                ov.model_copy(
                    update={
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "prompt": prompt,
                    }
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("dropping invalid overlay during repair", exc_info=True)

    return plan.model_copy(
        update={
            "timeline": Timeline(segments=segments),
            "operations": operations,
            "overlays": overlays,
            "output": OutputConfig(resolution=resolution, aspect_ratio=aspect),
        }
    )


def validate_edit_plan(plan: EditPlanDocument, *, duration: float) -> EditPlanDocument:
    """Raise EditPlanInvalidException if plan violates business rules."""
    errors: dict[str, list[str]] = {}
    total = duration if duration and duration > 0 else 0.0

    if total <= 0:
        errors.setdefault("duration", []).append("Source duration must be positive")

    segments = sorted(plan.timeline.segments, key=lambda s: s.start)
    prev_end = -1.0
    for seg in segments:
        key = f"timeline.segments.{seg.id}"
        if seg.end <= seg.start:
            errors.setdefault(key, []).append("end must be greater than start")
        if total > 0 and (seg.start < 0 or seg.end > total + 1e-6):
            errors.setdefault(key, []).append(f"segment outside [0, {total}]")
        if prev_end >= 0 and seg.start < prev_end - 1e-6:
            errors.setdefault(key, []).append("overlapping timeline segments")
        prev_end = max(prev_end, seg.end)

    if not segments and total > 0:
        # Empty timeline is invalid for a ready plan — at least one keep range
        errors.setdefault("timeline.segments", []).append("at least one segment required")

    for i, op in enumerate(plan.operations):
        op_type = getattr(op, "type", None)
        if op_type not in SUPPORTED_OPS:
            errors.setdefault(f"operations[{i}]", []).append(f"unknown op: {op_type}")
            continue
        if op_type == "zoom":
            if op.end <= op.start:
                errors.setdefault(f"operations[{i}]", []).append("zoom end must be > start")
            if total > 0 and (op.start < 0 or op.end > total + 1e-6):
                errors.setdefault(f"operations[{i}]", []).append("zoom outside source duration")

    if plan.output.aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
        errors.setdefault("output.aspect_ratio", []).append("unsupported aspect ratio")
    if plan.output.resolution not in SUPPORTED_RESOLUTIONS:
        errors.setdefault("output.resolution", []).append("unsupported resolution")

    if errors:
        raise EditPlanInvalidException("Invalid EditPlan", errors=errors)
    return plan


def ensure_valid_edit_plan(plan: EditPlanDocument, *, duration: float) -> EditPlanDocument:
    """Repair then validate; used after AI generation."""
    repaired = repair_edit_plan(plan, duration=duration)
    try:
        return validate_edit_plan(repaired, duration=duration)
    except EditPlanInvalidException:
        # Last clamp: force a single full-length keep
        total = duration if duration and duration > 0 else 30.0
        forced = repaired.model_copy(
            update={
                "timeline": Timeline(
                    segments=[
                        TimelineSegment(id="keep-1", start=0.0, end=round(total, 3))
                    ]
                ),
                "operations": [
                    op
                    for op in repaired.operations
                    if getattr(op, "type", None) == "crop"
                ],
            }
        )
        return validate_edit_plan(forced, duration=duration)
