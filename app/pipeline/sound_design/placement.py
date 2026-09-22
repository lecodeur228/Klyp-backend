"""Module 4 — SFX library + placement (scored, budgeted)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.pipeline.timeline.event_schema import (
    OverlayEvent,
    SfxCategory,
    SfxEvent,
    TransitionEvent,
    WordEvent,
    ZoomEvent,
)

LIBRARY_DIR = Path(__file__).resolve().parent / "sfx_library"
MANIFEST_PATH = LIBRARY_DIR / "manifest.json"

EVENT_TO_CATEGORY: dict[str, SfxCategory] = {
    "emphasis": "chime",
    "word_normal": "pop",
    "transition": "whoosh",
    "zoom": "riser",
    "overlay_cut": "swipe",
}

SFX_COOLDOWN_S = 0.15
MAX_SFX_PER_MIN = 8.0


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"assets": []}
    with MANIFEST_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def assets_for_category(category: SfxCategory) -> list[dict[str, Any]]:
    return [a for a in load_manifest().get("assets", []) if a.get("category") == category]


def resolve_asset_path(asset_id: str) -> Path | None:
    for a in load_manifest().get("assets", []):
        if a.get("id") == asset_id:
            rel = a.get("file")
            if not rel:
                return None
            path = LIBRARY_DIR / str(rel)
            return path if path.exists() else None
    return None


def _pick_asset(category: SfxCategory, *, index: int = 0) -> str | None:
    assets = assets_for_category(category)
    if not assets:
        return None
    return str(assets[index % len(assets)]["id"])


def place_sfx_events(
    *,
    duration: float,
    words: list[WordEvent],
    zooms: list[ZoomEvent],
    overlays: list[OverlayEvent],
    transitions: list[TransitionEvent] | None = None,
    relative_db: float = -5.0,
    dry_run: bool = False,
) -> tuple[list[SfxEvent], dict[str, Any]]:
    """Only fire on important events; enforce 150ms cooldown + per-minute budget."""
    candidates: list[tuple[float, SfxCategory, float]] = []

    for w in words:
        if w.important and w.emphasis:
            candidates.append((w.start, "chime", w.score))

    for z in zooms:
        if z.important:
            candidates.append((z.start, "riser", z.score))

    for ov in overlays:
        if ov.important:
            candidates.append((ov.start, "swipe", ov.score))

    for tr in transitions or []:
        if tr.kind != "cut" and tr.important:
            candidates.append((tr.start, "whoosh", tr.score))

    candidates.sort(key=lambda x: (-x[2], x[0]))
    max_n = max(1, int(round((duration / 60.0) * MAX_SFX_PER_MIN)))
    placed: list[SfxEvent] = []
    for t, cat, score in candidates:
        if len(placed) >= max_n:
            break
        if any(abs(t - e.start) < SFX_COOLDOWN_S for e in placed):
            continue
        asset_id = _pick_asset(cat, index=len(placed))
        placed.append(
            SfxEvent(
                id=f"sfx-{uuid4().hex[:10]}",
                start=t,
                end=t + 0.35,
                category=cat,
                asset_id=asset_id,
                volume_db=relative_db,
                score=score,
                important=True,
                meta={"dry_run": dry_run},
            )
        )
    placed.sort(key=lambda e: e.start)
    metrics = {
        "candidates": len(candidates),
        "placed": len(placed),
        "budget_max": max_n,
        "cooldown_s": SFX_COOLDOWN_S,
        "dry_run": dry_run,
    }
    return placed, metrics
