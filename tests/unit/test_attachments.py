"""Unit tests for vibe-edit attachment post-process."""

from __future__ import annotations

from app.pipeline.ai_edit.attachments import (
    apply_ai_edit_attachments,
    serialize_attachments,
    sfx_summary,
)
from app.schemas.editplan import (
    AiEditAttachment,
    AudioConfig,
    CaptionsConfig,
    EditPlanDocument,
    OutputConfig,
    Timeline,
    TimelineSegment,
)


def _base_plan(*, duration: float = 12.0) -> EditPlanDocument:
    return EditPlanDocument(
        schema_version="1.5.0",
        source_video_id="vid-1",
        timeline=Timeline(
            segments=[TimelineSegment(id="seg-0", start=0.0, end=duration)]
        ),
        operations=[],
        captions=CaptionsConfig(enabled=True, style="dynamic", language="fr"),
        visual_style="prism",
        overlays=[],
        audio=AudioConfig(denoise=True, normalize=True, sfx_enabled=True),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
        events={},
    )


def test_serialize_attachments_empty() -> None:
    assert serialize_attachments([]) == "[]"


def test_apply_image_attachment_creates_ready_overlay() -> None:
    plan = apply_ai_edit_attachments(
        _base_plan(),
        attachments=[
            AiEditAttachment(
                id="img-1",
                kind="image",
                url="https://cdn.example.com/photo.jpg",
                label="Logo",
            )
        ],
        prompt="mets mon logo en overlay",
        duration=12.0,
    )
    ready = [o for o in plan.overlays if o.status == "ready" and o.asset_url]
    assert len(ready) == 1
    assert ready[0].asset_url == "https://cdn.example.com/photo.jpg"
    assert ready[0].prompt == "Logo"


def test_apply_sfx_attachment_sets_prefs() -> None:
    plan = apply_ai_edit_attachments(
        _base_plan(),
        attachments=[
            AiEditAttachment(
                id="sfx-whoosh_01",
                kind="sfx",
                sfx_asset_id="whoosh_01",
                label="Whoosh",
                category="whoosh",
            )
        ],
        prompt="ajoute des whoosh",
        duration=12.0,
    )
    assert plan.audio.sfx_enabled is True
    vibe = (plan.events or {}).get("vibe") or {}
    assert "whoosh" in (vibe.get("preferred_sfx_categories") or [])
    # whoosh_01 exists in the procedural library
    assert "whoosh_01" in (vibe.get("preferred_sfx_asset_ids") or [])


def test_disable_sfx_via_prompt() -> None:
    plan = apply_ai_edit_attachments(
        _base_plan(),
        attachments=[],
        prompt="sans sfx s'il te plaît",
        duration=10.0,
    )
    assert plan.audio.sfx_enabled is False


def test_sfx_summary_counts_events() -> None:
    plan = _base_plan()
    plan = plan.model_copy(
        update={
            "events": {
                "events": [
                    {
                        "type": "sfx",
                        "id": "sfx-1",
                        "start": 1.0,
                        "end": 1.2,
                        "asset_id": "whoosh_01",
                        "category": "whoosh",
                        "relative_db": -5.0,
                    }
                ]
            }
        }
    )
    count, ids = sfx_summary(plan)
    assert count == 1
    assert ids == ["whoosh_01"]
