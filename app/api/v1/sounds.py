"""Sounds / SFX library API (Module 4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, RedirectResponse

from app.api.dependencies import CurrentUser, LocaleDep
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.i18n.messages import translate
from app.pipeline.sound_design.placement import (
    LIBRARY_DIR,
    assets_for_category,
    get_asset,
    load_manifest,
    resolve_asset_path,
    resolve_asset_url,
)

router = APIRouter(prefix="/sounds", tags=["sounds"])

SfxCategory = Literal["chime", "pop", "whoosh", "riser", "swipe"]


def _serialize_asset(a: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(a.get("id") or "")
    secure = a.get("secure_url")
    preview = (
        secure
        if isinstance(secure, str) and secure.startswith("http")
        else f"/sounds/{asset_id}/preview"
    )
    tags_raw = a.get("tags") or []
    tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []
    duration = a.get("duration_ms")
    return {
        "id": asset_id,
        "category": str(a.get("category") or ""),
        "label": str(a.get("label") or asset_id),
        "file": str(a.get("file") or ""),
        "tags": tags,
        "duration_ms": int(duration) if isinstance(duration, (int, float)) else None,
        "public_id": a.get("public_id"),
        "preview_url": preview,
        "storage": "cloudinary"
        if isinstance(secure, str) and secure.startswith("http")
        else "local",
    }


def _matches_query(asset: dict[str, Any], q: str) -> bool:
    needle = q.strip().lower()
    if not needle:
        return True
    tags = " ".join(str(t) for t in (asset.get("tags") or []))
    hay = (
        f"{asset.get('id', '')} {asset.get('label', '')} "
        f"{asset.get('category', '')} {asset.get('file', '')} {tags}"
    ).lower()
    return needle in hay


@router.get("")
async def list_sounds(
    user: CurrentUser,
    locale: LocaleDep,
    category: SfxCategory | None = Query(default=None),
    q: str | None = Query(default=None, max_length=80),
):
    _ = user
    manifest = load_manifest()
    raw: list[dict[str, Any]] = (
        assets_for_category(category) if category else list(manifest.get("assets") or [])
    )
    assets = [_serialize_asset(a) for a in raw if isinstance(a, dict) and a.get("id")]
    if q and q.strip():
        assets = [a for a in assets if _matches_query(a, q)]
    cats = sorted(
        {
            str(a.get("category"))
            for a in (manifest.get("assets") or [])
            if isinstance(a, dict) and a.get("category")
        }
    )
    return success_response(
        {
            "assets": assets,
            "categories": cats,
            "storage": manifest.get("storage") or "local",
            "folder": manifest.get("folder") or "klyp/sfx",
        },
        translate("ok", locale),
    )


@router.get("/{asset_id}/preview")
async def preview_sound(
    user: CurrentUser,
    asset_id: str,
):
    """Preview: redirect to Cloudinary CDN when available, else stream local/cache file."""
    _ = user
    asset = get_asset(asset_id)
    if not asset:
        raise NotFoundException("Sound asset not found")

    remote = resolve_asset_url(asset_id)
    if remote:
        return RedirectResponse(
            url=remote,
            status_code=302,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    # Prefer bundled local without forcing a download
    rel = asset.get("file")
    local: Path | None = None
    if isinstance(rel, str) and rel:
        candidate = LIBRARY_DIR / rel
        if candidate.exists():
            local = candidate
    if local is None:
        local = resolve_asset_path(asset_id)
    if local is None or not local.exists():
        raise NotFoundException("Sound asset not found")

    suffix = local.suffix.lower()
    media = (
        "audio/wav"
        if suffix == ".wav"
        else "audio/mpeg"
        if suffix in {".mp3", ".mpeg"}
        else "application/octet-stream"
    )
    return FileResponse(
        local,
        media_type=media,
        filename=local.name,
        headers={"Cache-Control": "private, max-age=3600"},
    )
