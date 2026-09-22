"""Versioned prompt registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    user_template: str
    metadata: dict[str, Any]


_REGISTRY: dict[str, PromptTemplate] = {
    "summarize": PromptTemplate(
        name="summarize",
        version="1.0.0",
        system="You are a concise assistant that summarizes text clearly.",
        user_template="Summarize the following text:\n\n{content}",
        metadata={"tags": ["summary"], "owner": "starter"},
    ),
    "extract_json": PromptTemplate(
        name="extract_json",
        version="1.0.0",
        system="You extract structured data and reply with JSON only.",
        user_template="Extract key facts from:\n\n{content}",
        metadata={"tags": ["structured"], "owner": "starter"},
    ),
    "edit_plan": PromptTemplate(
        name="edit_plan",
        version="1.0.0",
        system=(
            "You are Klyp's video editing planner. Reply with a single JSON object "
            "matching the EditPlan schema only — never FFmpeg commands or shell. "
            "Prefer removing silence (VAD), enabling captions, light zoom, and vertical output."
        ),
        user_template=(
            "User request:\n{prompt}\n\n"
            "Source video id: {source_video_id}\n"
            "Duration seconds: {duration}\n"
            "Transcript preview:\n{transcript}\n"
            "VAD silence segments:\n{vad}\n\n"
            "Produce a valid EditPlan JSON with schema_version 1.1.0, "
            "timeline.segments as keep ranges, operations, captions, visual_style, "
            "overlays (optional), audio, output."
        ),
        metadata={"tags": ["editplan", "klyp"], "owner": "product"},
    ),
    "creative_plan": PromptTemplate(
        name="creative_plan",
        version="1.4.0",
        system=(
            "You are Klyp's senior short-form video editor and creative director. "
            "Reply with a single JSON object only. Choose exactly one visual_style "
            "from: prism, paper, prime, elevate. "
            "Silence and filler words are already cut by the system — only place "
            "overlays inside the provided keep ranges (source timestamps). "
            "When a user brief is provided, prioritize that creative direction "
            "(pace, tone, overlays, caption energy) while staying inside keep ranges. "
            "Propose 0 to 5 illustrative overlays ONLY when a generated image clearly "
            "helps the viewer understand a spoken concept, object, place, or metaphor. "
            "Do not spam. Prefer fewer, stronger moments. "
            "Each overlay: start/end in SOURCE seconds (must lie inside a keep range), "
            "layout, kind, and a detailed English image prompt for GPT Image 2 "
            "(subject, style, lighting, composition; no text/watermark in the image). "
            "Typical overlay duration 1.5–3.5 seconds. Align start with the spoken beat. "
            "Layouts: plate = DEFAULT large centered insert (~60% width) for concepts; "
            "cover = full-frame cutaway for atmospheres/locations; "
            "accent = tiny corner pictogram ONLY for one ultra-simple icon. "
            "Majority MUST be plate or cover. accent at most once. "
            "kind: sticker for plate/accent, background for cover. "
            "Optional short reason field explaining why that beat needs an image."
        ),
        user_template=(
            "User brief (how to edit — follow closely when non-empty):\n{user_brief}\n\n"
            "Video id: {source_video_id}\n"
            "Source duration seconds: {duration}\n"
            "Aspect: {aspect}\n"
            "Keep ranges (source seconds — only place overlays inside these):\n"
            "{keep_ranges}\n\n"
            "Timed transcript (source seconds):\n{transcript}\n\n"
            "Return JSON matching this shape:\n"
            '{{"visual_style":"prism|paper|prime|elevate",'
            '"captions_mode":"minimal|dynamic",'
            '"overlays":[{{"start":0,"end":2.5,"layout":"plate",'
            '"kind":"sticker","prompt":"detailed English image prompt...",'
            '"reason":"why this beat"}}]}}'
        ),
        metadata={"tags": ["creative", "klyp"], "owner": "product"},
    ),
}


def get_prompt(name: str) -> PromptTemplate:
    if name not in _REGISTRY:
        raise KeyError(name)
    return _REGISTRY[name]


def render_prompt(name: str, **kwargs: str) -> tuple[str, str, str]:
    """Return (system, user, version)."""
    template = get_prompt(name)
    return template.system, template.user_template.format(**kwargs), template.version


def list_prompts() -> list[PromptTemplate]:
    return list(_REGISTRY.values())
