"""Unit tests for montage pipeline modules."""

from __future__ import annotations

from app.pipeline.ai_edit.editorial_rules import OverlaySpan, filter_overlays
from app.pipeline.effects.scoring import propose_zooms
from app.pipeline.enrich import enrich_edit_plan
from app.pipeline.sound_design.placement import place_sfx_events
from app.pipeline.timeline.builder import classify_emphasis, words_from_analysis_segments
from app.pipeline.timeline.event_schema import WordEvent
from app.pipeline.transcription.qa_check import evaluate_sync_qa
from app.schemas.editplan import EditPlanDocument, Timeline, TimelineSegment, VisualOverlay


def test_classify_emphasis():
    assert classify_emphasis("42") == "number"
    assert classify_emphasis("jamais") == "negation"
    assert classify_emphasis("IMPORTANT") == "proper"
    assert classify_emphasis("hello") is None


def test_qa_needs_review_on_drift():
    qa = evaluate_sync_qa(
        vad_segments=[{"start": 0, "end": 10}],
        segments=[
            {
                "id": "s1",
                "start": 0,
                "end": 5,
                "text": "hi",
                "words": [{"word": "hi", "start": 0, "end": 5}],
            }
        ],
        aligned=True,
    )
    assert qa["needs_review"] is True
    assert qa["drift_s"] >= 0.3


def test_presets_catalog_count():
    from app.pipeline.subtitles.presets_loader import (
        clear_preset_cache,
        list_catalog_preset_ids,
        list_preset_ids,
        load_preset,
        preset_to_ass_style,
    )

    clear_preset_cache()
    catalog = list_catalog_preset_ids()
    assert len(catalog) == 107
    assert "prism" in list_preset_ids()
    p = load_preset("001-hype-drop")
    assert p["id"] == "001-hype-drop"
    assert p["font"]["family"] == "Anton"
    ass = preset_to_ass_style(p)
    assert "primary" in ass
    assert ass["font"] == "Anton"
    pulse = load_preset("pulse")
    assert pulse.get("featured") is True


def test_zoom_budget_and_variety():
    words = [
        WordEvent(
            id=f"w{i}",
            start=float(i),
            end=float(i) + 0.3,
            text="IMPORTANT" if i % 3 == 0 else "ok",
            important=i % 3 == 0,
            emphasis="proper" if i % 3 == 0 else None,
            score=0.9 if i % 3 == 0 else 0.4,
        )
        for i in range(0, 60, 2)
    ]
    zooms, metrics = propose_zooms(duration=60.0, words=words)
    assert metrics["effects_placed"] <= metrics["budget_max"]
    assert len(zooms) >= 1
    kinds = [z.kind for z in zooms]
    for a, b in zip(kinds, kinds[1:]):
        assert a != b
    # At least one 5s+ gap without effect
    starts = [z.start for z in zooms]
    gaps_ok = False
    for i in range(len(starts) - 1):
        if starts[i + 1] - starts[i] >= 5.0:
            gaps_ok = True
    if len(starts) <= 1:
        gaps_ok = True
    assert gaps_ok or metrics["effects_placed"] <= 3


def test_sfx_cooldown():
    words = [
        WordEvent(
            id="w1",
            start=1.0,
            end=1.2,
            text="42",
            important=True,
            emphasis="number",
            score=0.95,
        ),
        WordEvent(
            id="w2",
            start=1.05,
            end=1.25,
            text="99",
            important=True,
            emphasis="number",
            score=0.95,
        ),
    ]
    sfx, metrics = place_sfx_events(
        duration=30.0, words=words, zooms=[], overlays=[]
    )
    assert metrics["placed"] <= 1
    assert len(sfx) <= 1


def test_editorial_no_cut_on_emphasis():
    words = [
        WordEvent(
            id="w",
            start=2.0,
            end=2.3,
            text="jamais",
            important=True,
            emphasis="negation",
            score=1.0,
        )
    ]
    spans = [OverlaySpan(id="o1", start=2.0, end=3.5, prompt="x")]
    kept, metrics = filter_overlays(spans, words=words)
    assert metrics["input"] == 1
    for ov in kept:
        assert abs(ov.start - 2.0) > 0.08 or ov.start >= 2.2


def test_enrich_attaches_events():
    plan = EditPlanDocument(
        source_video_id="vid",
        timeline=Timeline(segments=[TimelineSegment(id="k1", start=0, end=20)]),
        overlays=[
            VisualOverlay(
                id="ov1", start=5, end=7, prompt="a tip", layout="plate"
            )
        ],
    )
    segments = [
        {
            "id": "s1",
            "start": 0,
            "end": 5,
            "text": "hello 42",
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.4},
                {"word": "42", "start": 0.5, "end": 0.8},
            ],
        }
    ]
    enriched = enrich_edit_plan(
        plan=plan, duration=20.0, analysis_segments=segments, dry_run=True
    )
    assert enriched.schema_version == "1.5.0"
    assert enriched.events is not None
    assert enriched.events.get("metrics")
    assert any(op.type == "zoom" for op in enriched.operations) or enriched.events.get(
        "metrics", {}
    ).get("zoom")


def test_words_from_analysis():
    words = words_from_analysis_segments(
        [
            {
                "id": "s",
                "start": 0,
                "end": 1,
                "text": "x",
                "words": [{"word": "pas", "start": 0.1, "end": 0.3}],
            }
        ]
    )
    assert len(words) == 1
    assert words[0].emphasis == "negation"
    assert words[0].important is True
