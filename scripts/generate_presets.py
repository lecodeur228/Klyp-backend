#!/usr/bin/env python3
"""Generate subtitle preset JSON files from catalog.json (style-as-data).

Usage (from Klyp-backend):
  uv run python scripts/generate_presets.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "pipeline" / "subtitles" / "catalog.json"
OUT_DIR = ROOT / "app" / "pipeline" / "subtitles" / "presets"

CASE_MAP = {
    "UPPER": "uppercase",
    "MIXED": "mixed",
    "lower": "lowercase",
}

POS_MAP = {
    "BOTTOM": "bottom",
    "TOP": "top",
    "CENTER": "center",
}

FOND_MAP = {
    "NONE": "none",
    "PILL": "pill",
    "BOX": "box",
    "GRAD": "gradient",
    "WORDHL": "word_highlight",
    "LINE": "line",
}


def hex_to_ass(hex_color: str) -> str:
    """#RRGGBB → ASS &HAABBGGRR (opaque)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "&H00FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b.upper()}{g.upper()}{r.upper()}"


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def resolve_row(row: dict, lookups: dict) -> dict:
    fonts = lookups["fonts"]
    anims = lookups["animations"]
    palettes = lookups["palettes"]

    font = fonts[row["police"]]
    anim = anims[row["anim"]]
    pal = palettes[row["palette"]]
    bg_type = FOND_MAP[row["fond"]]
    bg_color = pal.get("background")
    accent = pal["accent"]
    # Dual accents: take first
    if "/" in accent:
        accent = accent.split("/")[0].strip()

    preset_id = f"{row['id']}-{slugify(row['name'])}"
    text = pal["text"]
    stroke_w = int(row["contour"])

    return {
        "id": preset_id,
        "name": row["name"],
        "label": row["name"],
        "category": row["category"],
        "featured": False,
        "font": {
            "family": font["family"],
            "weight": str(font["weight"]),
            "case": CASE_MAP[row["casse"]],
        },
        # Legacy flat fields for older loader paths
        "font_family": font["family"],
        "bold": int(font["weight"]) >= 700,
        "animation": anim["type"],
        "easing": anim["easing"],
        "safe_margin_v": 200 if row["position"] != "TOP" else 120,
        "colors": {
            "text": text,
            "highlight": accent,
            "css_text": text,
            "css_highlight": accent,
            "primary_ass": hex_to_ass(text),
            "highlight_ass": hex_to_ass(accent),
            "outline_ass": hex_to_ass("#000000") if stroke_w > 0 else "&H00000000",
        },
        "background": {
            "type": bg_type,
            "color": bg_color,
            "opacity": 0.7 if bg_type != "none" else 0.0,
        },
        "stroke": {
            "width": stroke_w,
            "color": "#000000",
        },
        "position": {
            "anchor": POS_MAP[row["position"]],
            "offset_y": 120,
        },
        "animation_detail": {
            "type": anim["type"],
            "duration_ms": anim["duration_ms"],
            "easing": anim["easing"],
        },
    }


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    lookups = {
        "fonts": catalog["fonts"],
        "animations": catalog["animations"],
        "palettes": catalog["palettes"],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove previously generated catalog presets (keep featured aliases)
    featured_keep = {"prism", "paper", "prime", "elevate", "pulse"}
    for path in OUT_DIR.glob("*.json"):
        if path.stem not in featured_keep:
            path.unlink()

    written = 0
    for row in catalog["styles"]:
        preset = resolve_row(row, lookups)
        out = OUT_DIR / f"{preset['id']}.json"
        out.write_text(json.dumps(preset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1

    # Featured aliases: map existing brand packs onto catalog looks (stable ids)
    aliases = {
        "prism": "001-hype-drop",
        "paper": "025-broadsheet",
        "prime": "007-main-character",
        "elevate": "040-old-money",
        "pulse": "029-arcade",
    }
    for alias_id, target_id in aliases.items():
        target_path = OUT_DIR / f"{target_id}.json"
        if not target_path.exists():
            continue
        data = json.loads(target_path.read_text(encoding="utf-8"))
        data["id"] = alias_id
        data["featured"] = True
        data["alias_of"] = target_id
        data["label"] = {
            "prism": "Prism",
            "paper": "Paper",
            "prime": "Prime",
            "elevate": "Elevate",
            "pulse": "Pulse",
        }[alias_id]
        data["name"] = data["label"]
        (OUT_DIR / f"{alias_id}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print(f"Wrote {written} catalog presets + {len(aliases)} featured aliases → {OUT_DIR}")


if __name__ == "__main__":
    main()
