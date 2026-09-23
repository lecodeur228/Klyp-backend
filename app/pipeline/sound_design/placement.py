"""Module 4 — SFX library + placement (scored, budgeted).

Assets live in `sfx_library/manifest.json`. Binaries may be:
- local files under `sfx_library/` (dev stubs), and/or
- Cloudinary (`public_id` + `secure_url`) after `scripts/import_sfx_cloudinary.py`.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.pipeline.timeline.event_schema import (
    OverlayEvent,
    SfxCategory,
    SfxEvent,
    TransitionEvent,
    WordEvent,
    ZoomEvent,
)

logger = logging.getLogger(__name__)

LIBRARY_DIR = Path(__file__).resolve().parent / "sfx_library"
MANIFEST_PATH = LIBRARY_DIR / "manifest.json"
CACHE_DIR = LIBRARY_DIR / ".cache"

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
        return {"assets": [], "storage": "local"}
    with MANIFEST_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {"assets": [], "storage": "local"}
    data.setdefault("assets", [])
    data.setdefault("storage", "local")
    return data


def clear_manifest_cache() -> None:
    load_manifest.cache_clear()


def save_manifest(data: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    clear_manifest_cache()


def get_asset(asset_id: str) -> dict[str, Any] | None:
    for a in load_manifest().get("assets", []):
        if a.get("id") == asset_id:
            return a if isinstance(a, dict) else None
    return None


def assets_for_category(category: SfxCategory | str) -> list[dict[str, Any]]:
    return [
        a
        for a in load_manifest().get("assets", [])
        if isinstance(a, dict) and a.get("category") == category
    ]


def resolve_asset_url(asset_id: str) -> str | None:
    asset = get_asset(asset_id)
    if not asset:
        return None
    url = asset.get("secure_url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None


def _suffix_for_asset(asset: dict[str, Any]) -> str:
    for key in ("file", "secure_url", "public_id"):
        raw = asset.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        path = raw.split("?", 1)[0]
        suf = Path(path).suffix.lower()
        if suf in {".wav", ".mp3", ".m4a", ".ogg", ".aac"}:
            return suf
    return ".wav"


def resolve_asset_path(asset_id: str) -> Path | None:
    """Local path for FFmpeg: prefer bundled file, else cache Cloudinary download."""
    asset = get_asset(asset_id)
    if not asset:
        return None

    rel = asset.get("file")
    if isinstance(rel, str) and rel:
        local = LIBRARY_DIR / rel
        if local.exists():
            return local

    url = resolve_asset_url(asset_id)
    if not url:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{asset_id}{_suffix_for_asset(asset)}"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            cached.write_bytes(resp.content)
        return cached
    except Exception:  # noqa: BLE001 — soft-fail missing SFX at render time
        logger.warning("Failed to download SFX %s from Cloudinary", asset_id, exc_info=True)
        if cached.exists():
            cached.unlink(missing_ok=True)
        return None


def _pick_asset(
    category: SfxCategory,
    *,
    salt: float = 0.0,
    preferred_ids: list[str] | None = None,
) -> str | None:
    preferred = preferred_ids or []
    for pid in preferred:
        asset = get_asset(pid)
        if asset and asset.get("category") == category:
            return pid
    # Prefer any preferred id that exists even if category differs (user tagged)
    for pid in preferred:
        if get_asset(pid):
            return pid
    assets = assets_for_category(category)
    if not assets:
        return None
    idx = int(abs(salt) * 1000) % len(assets)
    return str(assets[idx]["id"])


def place_sfx_events(
    *,
    duration: float,
    words: list[WordEvent],
    zooms: list[ZoomEvent],
    overlays: list[OverlayEvent],
    transitions: list[TransitionEvent] | None = None,
    relative_db: float = -5.0,
    dry_run: bool = False,
    enabled: bool = True,
    preferred_asset_ids: list[str] | None = None,
    preferred_categories: list[SfxCategory] | None = None,
    explicit_events: list[SfxEvent] | None = None,
) -> tuple[list[SfxEvent], dict[str, Any]]:
    """Only fire on important events; enforce 150ms cooldown + per-minute budget."""
    if not enabled:
        return [], {
            "candidates": 0,
            "placed": 0,
            "budget_max": 0,
            "cooldown_s": SFX_COOLDOWN_S,
            "dry_run": dry_run,
            "disabled": True,
        }

    if explicit_events:
        # Honor LLM/user explicit placements (light validation)
        placed = sorted(explicit_events, key=lambda e: e.start)
        metrics = {
            "candidates": len(placed),
            "placed": len(placed),
            "budget_max": len(placed),
            "cooldown_s": SFX_COOLDOWN_S,
            "dry_run": dry_run,
            "explicit": True,
        }
        return placed, metrics

    preferred_cats = preferred_categories or []
    candidates: list[tuple[float, SfxCategory, float]] = []

    for w in words:
        if w.important and w.emphasis:
            cat: SfxCategory = "chime"
            if preferred_cats:
                cat = preferred_cats[len(candidates) % len(preferred_cats)]
            candidates.append((w.start, cat, w.score))

    for z in zooms:
        if z.important:
            cat = "riser"
            if preferred_cats:
                cat = preferred_cats[len(candidates) % len(preferred_cats)]
            candidates.append((z.start, cat, z.score))

    for ov in overlays:
        if ov.important:
            cat = "swipe"
            if preferred_cats:
                cat = preferred_cats[len(candidates) % len(preferred_cats)]
            candidates.append((ov.start, cat, ov.score))

    for tr in transitions or []:
        if tr.kind != "cut" and tr.important:
            cat = "whoosh"
            if preferred_cats:
                cat = preferred_cats[len(candidates) % len(preferred_cats)]
            candidates.append((tr.start, cat, tr.score))

    # If user asked for a category but no candidates (quiet video), seed a few
    if preferred_cats and not candidates and duration > 0.5:
        step = max(1.5, duration / min(4, max(1, int(duration / 2))))
        t = min(0.8, duration * 0.1)
        while t < duration - 0.2 and len(candidates) < 4:
            cat = preferred_cats[len(candidates) % len(preferred_cats)]
            candidates.append((t, cat, 0.6))
            t += step

    candidates.sort(key=lambda x: (-x[2], x[0]))
    max_n = max(1, int(round((duration / 60.0) * MAX_SFX_PER_MIN)))
    if preferred_cats or preferred_asset_ids:
        max_n = max(max_n, min(6, max_n + 2))
    placed: list[SfxEvent] = []
    for t, cat, score in candidates:
        if len(placed) >= max_n:
            break
        if any(abs(t - e.start) < SFX_COOLDOWN_S for e in placed):
            continue
        asset_id = _pick_asset(
            cat, salt=t + len(placed) * 0.37, preferred_ids=preferred_asset_ids
        )
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
        "library_size": len(load_manifest().get("assets") or []),
        "preferred_assets": len(preferred_asset_ids or []),
        "preferred_categories": list(preferred_cats),
    }
    return placed, metrics
