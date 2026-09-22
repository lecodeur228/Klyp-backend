"""Subtitle preset catalog API (Module 2)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate
from app.pipeline.subtitles.presets_loader import (
    FEATURED_IDS,
    list_presets,
    load_preset,
    preset_to_preview_css,
)

router = APIRouter(prefix="/presets", tags=["presets"])


@router.get("")
async def list_subtitle_presets(
    user: CurrentUser,
    locale: LocaleDep,
    category: str | None = Query(default=None),
    featured: bool = Query(default=False),
):
    _ = user
    items = list_presets(category=category, featured_only=featured)
    categories = sorted(
        {str(i["category"]) for i in list_presets() if i.get("category") and not i.get("featured")}
    )
    return success_response(
        {
            "presets": items,
            "categories": categories,
            "featured_ids": list(FEATURED_IDS),
        },
        translate("ok", locale),
    )


@router.get("/{preset_id}")
async def get_subtitle_preset(
    preset_id: str,
    user: CurrentUser,
    locale: LocaleDep,
):
    _ = user
    data = load_preset(preset_id)
    return success_response(
        {
            "preset": data,
            "preview": preset_to_preview_css(data),
        },
        translate("ok", locale),
    )
