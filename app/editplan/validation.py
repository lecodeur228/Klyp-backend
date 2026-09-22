"""Business rules for EditPlan validation."""

from __future__ import annotations

from app.core.exceptions import EditPlanInvalidException
from app.schemas.editplan import EditPlanDocument

SUPPORTED_ASPECT_RATIOS = frozenset({"9:16", "16:9", "1:1", "4:5"})
SUPPORTED_RESOLUTIONS = frozenset({"720p", "1080p"})
SUPPORTED_OPS = frozenset({"zoom", "crop"})


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
