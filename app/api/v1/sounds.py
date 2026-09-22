"""Sounds / SFX library API (Module 4)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate
from app.pipeline.sound_design.placement import assets_for_category, load_manifest

router = APIRouter(prefix="/sounds", tags=["sounds"])

SfxCategory = Literal["chime", "pop", "whoosh", "riser", "swipe"]


@router.get("")
async def list_sounds(
    user: CurrentUser,
    locale: LocaleDep,
    category: SfxCategory | None = Query(default=None),
):
    _ = user
    manifest = load_manifest()
    raw: list[dict[str, Any]] = list(manifest.get("assets") or [])
    if category:
        raw = assets_for_category(category)
    assets = [
        {
            "id": str(a.get("id") or ""),
            "category": str(a.get("category") or ""),
            "label": str(a.get("label") or a.get("id") or ""),
            "file": str(a.get("file") or ""),
        }
        for a in raw
        if a.get("id")
    ]
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
