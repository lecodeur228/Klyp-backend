"""Sounds / SFX library API (Module 4)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.dependencies import CurrentUser, LocaleDep
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.i18n.messages import translate
from app.pipeline.sound_design.placement import (
    assets_for_category,
    load_manifest,
    resolve_asset_path,
)

router = APIRouter(prefix="/sounds", tags=["sounds"])

SfxCategory = Literal["chime", "pop", "whoosh", "riser", "swipe"]


def _serialize_assets(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": str(a.get("id") or ""),
            "category": str(a.get("category") or ""),
            "label": str(a.get("label") or a.get("id") or ""),
            "file": str(a.get("file") or ""),
        }
        for a in raw
        if a.get("id")
    ]


def _matches_query(asset: dict[str, str], q: str) -> bool:
    needle = q.strip().lower()
    if not needle:
        return True
    hay = f"{asset['id']} {asset['label']} {asset['category']} {asset['file']}".lower()
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
    assets = _serialize_assets(raw)
    if q and q.strip():
        assets = [a for a in assets if _matches_query(a, q)]
    cats = sorted(
        {
            str(a.get("category"))
            for a in (manifest.get("assets") or [])
            if a.get("category")
        }
    )
    return success_response(
        {"assets": assets, "categories": cats},
        translate("ok", locale),
    )


@router.get("/{asset_id}/preview")
async def preview_sound(
    user: CurrentUser,
    asset_id: str,
):
    """Stream a library SFX file for in-editor preview playback."""
    _ = user
    path = resolve_asset_path(asset_id)
    if path is None:
        raise NotFoundException("Sound asset not found")
    suffix = path.suffix.lower()
    media = "audio/wav" if suffix == ".wav" else "audio/mpeg" if suffix in {".mp3", ".mpeg"} else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        headers={"Cache-Control": "private, max-age=3600"},
    )
