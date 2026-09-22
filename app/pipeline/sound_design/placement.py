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


def _pick_asset(category: SfxCategory, *, salt: float = 0.0) -> str | None:
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
        asset_id = _pick_asset(cat, salt=t + len(placed) * 0.37)
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
    }
    return placed, metrics
