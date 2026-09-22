"""Module 2 — subtitle style presets (JSON-driven, catalog-backed)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PRESETS_DIR = Path(__file__).resolve().parent / "presets"
FEATURED_IDS = ("prism", "paper", "prime", "elevate", "pulse")


def _font_family(preset: dict[str, Any]) -> str:
    font = preset.get("font")
    if isinstance(font, dict):
        return str(font.get("family") or "Arial")
    return str(preset.get("font_family") or preset.get("font") or "Arial")


def _font_case(preset: dict[str, Any]) -> str:
    font = preset.get("font")
    if isinstance(font, dict):
        return str(font.get("case") or "mixed")
    return "mixed"


def _colors(preset: dict[str, Any]) -> dict[str, Any]:
    return dict(preset.get("colors") or {})


@lru_cache(maxsize=1)
def list_preset_ids() -> tuple[str, ...]:
    if not PRESETS_DIR.exists():
        return ()
    return tuple(sorted(p.stem for p in PRESETS_DIR.glob("*.json")))


@lru_cache(maxsize=1)
def list_catalog_preset_ids() -> tuple[str, ...]:
    """Numeric catalog ids only (exclude featured aliases)."""
    return tuple(i for i in list_preset_ids() if i[:1].isdigit())


@lru_cache(maxsize=256)
def load_preset(preset_id: str) -> dict[str, Any]:
    path = PRESETS_DIR / f"{preset_id}.json"
    if not path.exists():
        # Try featured fallback then first catalog
        for fallback in ("prism", "001-hype-drop", "prime"):
            alt = PRESETS_DIR / f"{fallback}.json"
            if alt.exists():
                path = alt
                break
        else:
            return {
                "id": preset_id,
                "label": preset_id,
                "name": preset_id,
                "font": {"family": "Arial", "weight": "700", "case": "mixed"},
                "colors": {
                    "text": "#FFFFFF",
                    "highlight": "#3EC6FF",
                    "css_text": "#FFFFFF",
                    "css_highlight": "#3EC6FF",
                    "primary_ass": "&H00FFFFFF",
                    "highlight_ass": "&H00FFFFFF",
                    "outline_ass": "&H00000000",
                },
                "animation": "pop_scale",
                "safe_margin_v": 200,
            }
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def list_presets(
    *,
    category: str | None = None,
    featured_only: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pid in list_preset_ids():
        if featured_only and pid not in FEATURED_IDS:
            continue
        if not featured_only and pid in FEATURED_IDS:
            # Still include featured when listing all, but catalog browse
            # typically filters them out client-side.
            pass
        data = load_preset(pid)
        if category and data.get("category") != category:
            continue
        items.append(
            {
                "id": data.get("id") or pid,
                "name": data.get("name") or data.get("label") or pid,
                "category": data.get("category"),
                "featured": bool(data.get("featured") or pid in FEATURED_IDS),
                "colors": {
                    "text": (_colors(data).get("text") or _colors(data).get("css_text")),
                    "highlight": (
                        _colors(data).get("highlight") or _colors(data).get("css_highlight")
                    ),
                },
                "font_family": _font_family(data),
                "animation": data.get("animation")
                or (data.get("animation_detail") or {}).get("type"),
            }
        )
    return items


def preset_to_ass_style(preset: dict[str, Any]) -> dict[str, str]:
    """Map preset JSON → ASS Theme style keys used by render/ass.py."""
    colors = _colors(preset)
    stroke = preset.get("stroke") or {}
    stroke_w = int(stroke.get("width") or 0)
    anim = preset.get("animation_detail") or {}
    position = preset.get("position") or {}
    anchor = str(position.get("anchor") or "bottom")
    margin = 200
    if anchor == "top":
        margin = 120
    elif anchor == "center":
        margin = 480
    outline = colors.get("outline_ass")
    if not outline:
        outline = "&H00000000" if stroke_w <= 0 else "&H00000000"

    weight = "700"
    font_obj = preset.get("font")
    if isinstance(font_obj, dict):
        weight = str(font_obj.get("weight") or "700")
    bold = "-1" if (preset.get("bold") or int(weight) >= 700) else "0"

    return {
        "name": str(preset.get("label") or preset.get("name") or preset.get("id") or "Preset"),
        "font": _font_family(preset),
        "primary": str(colors.get("primary_ass") or "&H00FFFFFF"),
        "secondary": str(
            colors.get("highlight_ass") or colors.get("primary_ass") or "&H00FFFFFF"
        ),
        "outline": str(outline),
        "bold": bold,
        "animation": str(
            anim.get("type") or preset.get("animation") or "pop_scale"
        ),
        "easing": str(anim.get("easing") or preset.get("easing") or "ease-out-back"),
        "safe_margin_v": str(int(preset.get("safe_margin_v") or margin)),
        "stroke_width": str(stroke_w),
        "case": _font_case(preset),
        "anchor": anchor,
    }


def preset_to_preview_css(preset: dict[str, Any]) -> dict[str, Any]:
    """Flat CSS-oriented dict for web caption overlay."""
    colors = _colors(preset)
    bg = preset.get("background") or {}
    stroke = preset.get("stroke") or {}
    anim = preset.get("animation_detail") or {}
    position = preset.get("position") or {}
    return {
        "id": preset.get("id"),
        "fontFamily": _font_family(preset),
        "fontWeight": (
            str((preset.get("font") or {}).get("weight"))
            if isinstance(preset.get("font"), dict)
            else "700"
        ),
        "textCase": _font_case(preset),
        "color": colors.get("css_text") or colors.get("text") or "#FFFFFF",
        "highlight": colors.get("css_highlight") or colors.get("highlight") or "#3EC6FF",
        "backgroundType": bg.get("type") or "none",
        "backgroundColor": bg.get("color"),
        "backgroundOpacity": bg.get("opacity", 0.7),
        "strokeWidth": int(stroke.get("width") or 0),
        "strokeColor": stroke.get("color") or "#000000",
        "anchor": position.get("anchor") or "bottom",
        "animation": anim.get("type") or preset.get("animation") or "pop_scale",
        "durationMs": int(anim.get("duration_ms") or 180),
        "easing": anim.get("easing") or "ease-out",
    }


def clear_preset_cache() -> None:
    list_preset_ids.cache_clear()
    list_catalog_preset_ids.cache_clear()
    load_preset.cache_clear()
