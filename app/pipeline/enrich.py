"""Compose Modules 2/3/4/5 onto an EditPlan + analysis → event timeline."""

from __future__ import annotations

from typing import Any

from app.pipeline.ai_edit.attachments import (
    extract_explicit_sfx_events,
    extract_sfx_prefs,
)
from app.pipeline.ai_edit.editorial_rules import (
    OverlaySpan,
    build_contextual_prompt,
    filter_overlays,
)
from app.pipeline.effects.scoring import propose_zooms
from app.pipeline.sound_design.placement import place_sfx_events
from app.pipeline.timeline.builder import (
    build_event_timeline,
    words_from_analysis_segments,
)
from app.pipeline.timeline.event_schema import OverlayEvent, ZoomEvent
from app.schemas.editplan import EditPlanDocument, VisualOverlay, ZoomOperation


def enrich_edit_plan(
    *,
    plan: EditPlanDocument,
    duration: float,
    analysis_segments: list[dict[str, Any]] | None,
    global_subject: str | None = None,
    art_direction: str | None = None,
    needs_review: bool = False,
    dry_run: bool = False,
    zoom_budget_per_min: float = 4.0,
) -> EditPlanDocument:
    """Apply editorial rules, zoom scoring, SFX placement; attach events JSON."""
    words = words_from_analysis_segments(analysis_segments)

    # Module 3 — editorial constraints on overlays
    # Keep user-attached ready overlays with asset_url intact (don't rewrite prompt)
    attached_ready = {
        ov.id
        for ov in plan.overlays
        if ov.status == "ready"
        and isinstance(ov.asset_url, str)
        and ov.asset_url.startswith("http")
    }
    spans = [
        OverlaySpan(
            id=ov.id,
            start=float(ov.start),
            end=float(ov.end),
            prompt=ov.prompt,
            layout=ov.layout,
        )
        for ov in plan.overlays
        if ov.status != "rejected"
    ]
    filtered, editorial_metrics = filter_overlays(spans, words=words)
    subject = (global_subject or "").strip() or "creator talking-head"
    art = (art_direction or "").strip() or f"{plan.visual_style} social video palette"
    by_id = {ov.id: ov for ov in plan.overlays}
    new_overlays: list[VisualOverlay] = []
    for span in filtered:
        base = by_id.get(span.id)
        if base and base.id in attached_ready:
            new_overlays.append(
                base.model_copy(
                    update={
                        "start": span.start,
                        "end": span.end,
                        "layout": span.layout,
                    }
                )
            )
            continue
        prompt = build_contextual_prompt(
            local_phrase=span.prompt,
            global_subject=subject,
            art_direction=art,
        )
        if base:
            new_overlays.append(
                base.model_copy(
                    update={
                        "start": span.start,
                        "end": span.end,
                        "prompt": prompt,
                        "layout": span.layout,
                    }
                )
            )
        else:
            new_overlays.append(
                VisualOverlay(
                    id=span.id,
                    start=span.start,
                    end=span.end,
                    prompt=prompt,
                    layout=span.layout,  # type: ignore[arg-type]
                )
            )

    # Module 5 — zoom proposals → operations
    zooms, zoom_metrics = propose_zooms(
        duration=duration,
        words=words,
        budget_per_min=zoom_budget_per_min,
        dry_run=dry_run,
    )
    zoom_ops = [
        ZoomOperation(start=z.start, end=z.end, scale=z.scale) for z in zooms
    ]
    # Preserve non-zoom ops (crop) from the incoming plan
    preserved = [
        op for op in plan.operations if getattr(op, "type", None) != "zoom"
    ]
    operations = list(preserved) + zoom_ops

    overlay_events = [
        OverlayEvent(
            id=f"ov-{ov.id}",
            start=float(ov.start),
            end=float(ov.end),
            overlay_id=ov.id,
            layout=ov.layout,
            prompt=ov.prompt,
            score=0.75,
            important=ov.layout in {"plate", "cover"},
        )
        for ov in new_overlays
    ]

    preferred_ids, preferred_cats = extract_sfx_prefs(plan)
    explicit_sfx = extract_explicit_sfx_events(plan)

    # Module 4 — SFX on important events
    sfx_events, sfx_metrics = place_sfx_events(
        duration=duration,
        words=words,
        zooms=zooms,
        overlays=overlay_events,
        relative_db=plan.audio.sfx_relative_db,
        dry_run=dry_run,
        enabled=bool(plan.audio.sfx_enabled),
        preferred_asset_ids=preferred_ids or None,
        preferred_categories=preferred_cats or None,
        explicit_events=explicit_sfx or None,
    )

    # Preserve vibe prefs bag across rebuild
    vibe_bag = {}
    if isinstance(plan.events, dict) and isinstance(plan.events.get("vibe"), dict):
        vibe_bag = dict(plan.events["vibe"])

    draft = plan.model_copy(
        update={
            "schema_version": "1.5.0",
            "overlays": new_overlays,
            "operations": operations,
        }
    )
    timeline = build_event_timeline(
        video_id=plan.source_video_id,
        duration=duration,
        plan=draft,
        analysis_segments=analysis_segments,
        needs_review=needs_review,
        dry_run=dry_run,
        metrics={
            "editorial": editorial_metrics,
            "zoom": zoom_metrics,
            "sfx": sfx_metrics,
        },
    )
    # Append zoom + sfx events (builder already has words/overlays/keeps)
    extra = list(timeline.events)
    # Replace auto zoom events from operations with detailed ZoomEvent kinds
    extra = [e for e in extra if e.type != "zoom"]
    extra.extend(zooms)
    extra.extend(sfx_events)
    extra.sort(key=lambda e: (e.start, e.end, e.type))
    timeline = timeline.model_copy(update={"events": extra})

    data = draft.model_dump()
    events_dump = timeline.model_dump()
    if vibe_bag:
        events_dump["vibe"] = vibe_bag
    data["events"] = events_dump
    return EditPlanDocument.model_validate(data)


def zoom_events_from_plan(plan: EditPlanDocument) -> list[ZoomEvent]:
    events = (plan.events or {}).get("events") or []
    out: list[ZoomEvent] = []
    for raw in events:
        if not isinstance(raw, dict) or raw.get("type") != "zoom":
            continue
        try:
            out.append(ZoomEvent.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return out
