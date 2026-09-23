"""Deterministic post-process for vibe-edit attachments (media + SFX)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.pipeline.sound_design.placement import get_asset
from app.pipeline.timeline.event_schema import SfxCategory, SfxEvent
from app.schemas.editplan import AiEditAttachment, EditPlanDocument, VisualOverlay

_SFX_WORDS = {
    "sfx",
    "sound",
    "sounds",
    "whoosh",
    "chime",
    "riser",
    "swipe",
    "pop",
    "effet",
    "effets",
    "sonore",
    "sonores",
    "bruitage",
    "bruitages",
}

_CAT_HINTS: list[tuple[str, SfxCategory]] = [
    ("whoosh", "whoosh"),
    ("chime", "chime"),
    ("riser", "riser"),
    ("swipe", "swipe"),
    ("pop", "pop"),
    ("carillon", "chime"),
    ("transition", "whoosh"),
]


def _prompt_wants_sfx(prompt: str) -> bool:
    low = prompt.lower()
    if any(w in low for w in ("sans sfx", "no sfx", "disable sfx", "pas de sfx", "sans effet")):
        return False
    return any(w in low for w in _SFX_WORDS)


def _prompt_disables_sfx(prompt: str) -> bool:
    low = prompt.lower()
    return any(
        w in low
        for w in ("sans sfx", "no sfx", "disable sfx", "pas de sfx", "sans effet sonore")
    )


def _categories_from_prompt(prompt: str) -> list[SfxCategory]:
    low = prompt.lower()
    found: list[SfxCategory] = []
    for needle, cat in _CAT_HINTS:
        if needle in low and cat not in found:
            found.append(cat)
    return found


def serialize_attachments(attachments: list[AiEditAttachment]) -> str:
    if not attachments:
        return "[]"
    rows: list[dict[str, Any]] = []
    for a in attachments:
        rows.append(
            {
                "id": a.id,
                "kind": a.kind,
                "url": a.url,
                "label": a.label,
                "sfx_asset_id": a.sfx_asset_id,
                "category": a.category,
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def timed_transcript(segments: list[dict[str, Any]] | None, *, limit: int = 80) -> str:
    lines: list[str] = []
    for seg in (segments or [])[:limit]:
        if not isinstance(seg, dict) or not seg.get("text"):
            continue
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue
        lines.append(f"[{start:.2f}-{end:.2f}] {str(seg['text']).strip()}")
    return "\n".join(lines)[:12000] or "(empty)"


def apply_ai_edit_attachments(
    plan: EditPlanDocument,
    *,
    attachments: list[AiEditAttachment],
    prompt: str,
    duration: float,
) -> EditPlanDocument:
    """Force attached images onto overlays and wire SFX preferences into plan meta."""
    total = duration if duration > 0 else 30.0
    overlays = list(plan.overlays)
    used_urls = {
        (ov.asset_url or "").strip()
        for ov in overlays
        if isinstance(ov.asset_url, str) and ov.asset_url.strip()
    }

    image_atts = [
        a
        for a in attachments
        if a.kind in {"image", "video"} and isinstance(a.url, str) and a.url.startswith("http")
    ]
    # Spread attached media across the first keep / full duration
    keeps = [(s.start, s.end) for s in plan.timeline.segments if s.end > s.start]
    if not keeps:
        keeps = [(0.0, total)]

    for i, att in enumerate(image_atts):
        url = (att.url or "").strip()
        if not url or url in used_urls:
            # Still upgrade existing overlay if URL match missing status
            continue
        keep = keeps[i % len(keeps)]
        span = min(2.8, max(1.4, (keep[1] - keep[0]) * 0.35))
        start = keep[0] + min(0.4, max(0.0, (keep[1] - keep[0] - span) * 0.2))
        end = min(keep[1], start + span)
        if end <= start:
            start = keep[0]
            end = min(keep[1], keep[0] + span)
        layout = "cover" if att.kind == "video" or i == 0 and "cover" in prompt.lower() else "plate"
        if "cover" in prompt.lower():
            layout = "cover"
        overlays.append(
            VisualOverlay(
                id=f"att-{uuid4().hex[:10]}",
                start=round(start, 3),
                end=round(end, 3),
                kind="background" if layout == "cover" else "sticker",
                layout=layout,  # type: ignore[arg-type]
                prompt=(att.label or "User media").strip()[:500] or "User media",
                status="ready",
                asset_url=url,
            )
        )
        used_urls.add(url)

    # Prefer LLM overlays that already used attachment URLs — mark ready
    att_urls = {((a.url or "").strip()) for a in image_atts if a.url}
    fixed: list[VisualOverlay] = []
    for ov in overlays:
        url = (ov.asset_url or "").strip()
        if url and url in att_urls and ov.status in {"proposed", "accepted"}:
            fixed.append(ov.model_copy(update={"status": "ready"}))
        else:
            fixed.append(ov)

    sfx_atts = [a for a in attachments if a.kind == "sfx"]
    preferred_ids: list[str] = []
    preferred_cats: list[str] = []
    for a in sfx_atts:
        aid = (a.sfx_asset_id or a.id or "").strip()
        if aid and get_asset(aid):
            preferred_ids.append(aid)
            asset = get_asset(aid)
            if asset and asset.get("category"):
                preferred_cats.append(str(asset["category"]))
        elif a.category:
            preferred_cats.append(str(a.category))

    preferred_cats.extend(_categories_from_prompt(prompt))
    # dedupe preserve order
    seen_c: set[str] = set()
    cats: list[str] = []
    for c in preferred_cats:
        if c in {"chime", "pop", "whoosh", "riser", "swipe"} and c not in seen_c:
            seen_c.add(c)
            cats.append(c)

    audio = plan.audio
    if _prompt_disables_sfx(prompt):
        audio = audio.model_copy(update={"sfx_enabled": False})
    elif sfx_atts or _prompt_wants_sfx(prompt) or cats or preferred_ids:
        audio = audio.model_copy(update={"sfx_enabled": True})

    events = dict(plan.events) if isinstance(plan.events, dict) else {}
    vibe_meta = dict(events.get("vibe") or {}) if isinstance(events.get("vibe"), dict) else {}
    vibe_meta["preferred_sfx_asset_ids"] = preferred_ids
    vibe_meta["preferred_sfx_categories"] = cats
    vibe_meta["attachments"] = [
        {
            "id": a.id,
            "kind": a.kind,
            "url": a.url,
            "sfx_asset_id": a.sfx_asset_id,
            "category": a.category,
        }
        for a in attachments
    ]
    events["vibe"] = vibe_meta

    return plan.model_copy(
        update={
            "overlays": fixed,
            "audio": audio,
            "events": events,
        }
    )


def extract_sfx_prefs(plan: EditPlanDocument) -> tuple[list[str], list[SfxCategory]]:
    events = plan.events if isinstance(plan.events, dict) else {}
    vibe = events.get("vibe") if isinstance(events, dict) else None
    ids: list[str] = []
    cats: list[SfxCategory] = []
    if isinstance(vibe, dict):
        for raw in vibe.get("preferred_sfx_asset_ids") or []:
            if isinstance(raw, str) and raw.strip():
                ids.append(raw.strip())
        for raw in vibe.get("preferred_sfx_categories") or []:
            if raw in {"chime", "pop", "whoosh", "riser", "swipe"}:
                cats.append(raw)  # type: ignore[arg-type]
    return ids, cats


def extract_explicit_sfx_events(plan: EditPlanDocument) -> list[SfxEvent]:
    """Pull any LLM-authored sfx rows already present in events.events."""
    raw_events = []
    if isinstance(plan.events, dict):
        raw_events = plan.events.get("events") or []
    out: list[SfxEvent] = []
    if not isinstance(raw_events, list):
        return out
    for raw in raw_events:
        if not isinstance(raw, dict) or raw.get("type") != "sfx":
            continue
        try:
            out.append(SfxEvent.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


def sfx_summary(plan: EditPlanDocument) -> tuple[int, list[str]]:
    events = []
    if isinstance(plan.events, dict):
        events = plan.events.get("events") or []
    ids: list[str] = []
    count = 0
    if isinstance(events, list):
        for raw in events:
            if not isinstance(raw, dict) or raw.get("type") != "sfx":
                continue
            count += 1
            aid = raw.get("asset_id")
            if isinstance(aid, str) and aid and aid not in ids:
                ids.append(aid)
    return count, ids
