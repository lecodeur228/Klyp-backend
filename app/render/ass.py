"""Build ASS subtitle files from EditPlan captions + transcript cues."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline.subtitles.presets_loader import load_preset, preset_to_ass_style
from app.schemas.editplan import (
    CaptionPosition,
    CaptionScale,
    EditPlanDocument,
    VisualStyle,
)

# Legacy inline themes kept as fallback if preset JSON missing.
THEME_STYLES: dict[str, dict[str, str]] = {
    "prism": {
        "name": "Prism",
        "font": "Arial",
        "primary": "&H00FFFFFF",
        "secondary": "&H00FFFFFF",
        "outline": "&H00000000",
        "bold": "-1",
    },
    "paper": {
        "name": "Paper",
        "font": "Georgia",
        "primary": "&H0010151A",
        "secondary": "&H0040A060",
        "outline": "&H00E4EFF4",
        "bold": "0",
    },
    "prime": {
        "name": "Prime",
        "font": "Arial Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H00FCD37D",
        "outline": "&H00404040",
        "bold": "-1",
    },
    "elevate": {
        "name": "Elevate",
        "font": "Georgia",
        "primary": "&H00FFFFFF",
        "secondary": "&H00FFFFFF",
        "outline": "&H00202020",
        "bold": "0",
    },
    "pulse": {
        "name": "Pulse",
        "font": "Helvetica Neue",
        "primary": "&H00F5F5F5",
        "secondary": "&H0048E0A0",
        "outline": "&H00101010",
        "bold": "-1",
    },
}

# ASS Alignment: 2 = bottom-center, 8 = top-center (PlayRes 1080x1920)
# MarginV keeps text above TikTok/Reels UI chrome (safe zone).
POSITION_LAYOUT: dict[CaptionPosition, dict[str, str]] = {
    "bottom": {"alignment": "2", "margin_v": "96"},
    "lower": {"alignment": "2", "margin_v": "200"},
    "top": {"alignment": "8", "margin_v": "120"},
}

SCALE_SIZE: dict[CaptionScale, str] = {
    "sm": "42",
    "md": "52",
    "lg": "64",
}


def _resolve_theme(style: VisualStyle) -> dict[str, str]:
    try:
        preset = load_preset(style)
        return preset_to_ass_style(preset)
    except Exception:  # noqa: BLE001
        return THEME_STYLES.get(style, THEME_STYLES["prime"])



def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _karaoke_line(words: list[dict[str, Any]], *, cue_start: float, cue_end: float) -> str:
    """Build ASS karaoke text with \\k tags (centiseconds per word)."""
    parts: list[str] = []
    for w in words:
        token = _escape_ass(str(w.get("word") or ""))
        if not token:
            continue
        try:
            ws = float(w.get("start", cue_start))
            we = float(w.get("end", ws))
        except (TypeError, ValueError):
            continue
        dur_cs = max(1, int(round((we - ws) * 100)))
        # Emphasize numbers / short punch words with slight scale via \fsc
        emph = token.replace(",", "").replace(".", "")
        if emph.isdigit() or (len(token) <= 12 and token.isupper() and token.isalpha()):
            parts.append(f"{{\\k{dur_cs}\\fscx108\\fscy108}}{token}{{\\fscx100\\fscy100}}")
        else:
            parts.append(f"{{\\k{dur_cs}}}{token}")
    if parts:
        return " ".join(parts)
    return ""


def build_ass_from_cues(
    *,
    plan: EditPlanDocument,
    cues: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    theme = _resolve_theme(plan.visual_style)
    position = plan.captions.position if plan.captions.position in POSITION_LAYOUT else "lower"
    scale = plan.captions.scale if plan.captions.scale in SCALE_SIZE else "md"
    layout = POSITION_LAYOUT[position]  # type: ignore[index]
    fontsize = SCALE_SIZE[scale]  # type: ignore[index]
    secondary = theme.get("secondary", "&H000000FF")
    margin_v = theme.get("safe_margin_v") or layout["margin_v"]
    outline_w = theme.get("stroke_width") or "3"
    # Prefer preset anchor when captions.position is default lower
    anchor = theme.get("anchor") or "bottom"
    if plan.captions.position == "lower" and anchor in {"top", "center", "bottom"}:
        if anchor == "top":
            layout = POSITION_LAYOUT["top"]
            margin_v = theme.get("safe_margin_v") or "120"
        elif anchor == "center":
            layout = {"alignment": "5", "margin_v": theme.get("safe_margin_v") or "480"}
        else:
            layout = POSITION_LAYOUT["lower"]



    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{theme["font"]},{fontsize},{theme["primary"]},{secondary},{theme["outline"]},&H64000000,{theme["bold"]},0,0,0,100,100,0,0,1,{outline_w},1,{layout["alignment"]},48,48,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        start = float(cue.get("start", 0))
        end = float(cue.get("end", start + 1))
        text = str(cue.get("text") or "").strip()
        words = list(cue.get("words") or [])
        if end <= start:
            continue
        karaoke = _karaoke_line(words, cue_start=start, cue_end=end) if words else ""
        body = karaoke or _escape_ass(text)
        if not body:
            continue
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{body}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    return output_path
