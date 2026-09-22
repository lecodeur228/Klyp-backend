"""Module 3 — hard editorial rules for B-roll / transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.pipeline.timeline.event_schema import WordEvent

MIN_BROLL_S = 1.2
MAX_BROLL_S = 4.0
ELABORATE_TRANSITION_COOLDOWN_S = 17.0


@dataclass(slots=True)
class OverlaySpan:
    id: str
    start: float
    end: float
    prompt: str
    layout: str = "plate"


def clamp_broll_duration(start: float, end: float) -> tuple[float, float]:
    dur = end - start
    if dur < MIN_BROLL_S:
        end = start + MIN_BROLL_S
    elif dur > MAX_BROLL_S:
        end = start + MAX_BROLL_S
    return start, end


def cuts_on_emphasis(start: float, end: float, words: list[WordEvent], *, tol: float = 0.08) -> bool:
    for w in words:
        if not w.important:
            continue
        if abs(w.start - start) <= tol or abs(w.end - start) <= tol:
            return True
        if abs(w.start - end) <= tol or abs(w.end - end) <= tol:
            return True
    return False


def enforce_return_to_speaker(overlays: list[OverlaySpan]) -> list[OverlaySpan]:
    """After a B-roll sequence, require a speaker gap before the next overlay."""
    if not overlays:
        return []
    sorted_ov = sorted(overlays, key=lambda o: o.start)
    kept: list[OverlaySpan] = [sorted_ov[0]]
    for ov in sorted_ov[1:]:
        prev = kept[-1]
        gap = ov.start - prev.end
        if gap < 0.35:
            # Push start after a speaker beat
            new_start = prev.end + 0.6
            dur = ov.end - ov.start
            kept.append(
                OverlaySpan(
                    id=ov.id,
                    start=new_start,
                    end=new_start + dur,
                    prompt=ov.prompt,
                    layout=ov.layout,
                )
            )
        else:
            kept.append(ov)
    return kept


def filter_overlays(
    overlays: list[OverlaySpan],
    *,
    words: list[WordEvent],
) -> tuple[list[OverlaySpan], dict[str, Any]]:
    """Apply hard editorial constraints; return filtered list + metrics."""
    cleaned: list[OverlaySpan] = []
    rejected = 0
    for ov in overlays:
        start, end = clamp_broll_duration(ov.start, ov.end)
        if cuts_on_emphasis(start, end, words):
            # Nudge off the emphasis word
            start += 0.25
            start, end = clamp_broll_duration(start, end)
            if cuts_on_emphasis(start, end, words):
                rejected += 1
                continue
        cleaned.append(
            OverlaySpan(id=ov.id, start=start, end=end, prompt=ov.prompt, layout=ov.layout)
        )
    cleaned = enforce_return_to_speaker(cleaned)
    metrics = {
        "input": len(overlays),
        "kept": len(cleaned),
        "rejected_emphasis": rejected,
        "min_broll_s": MIN_BROLL_S,
        "max_broll_s": MAX_BROLL_S,
    }
    return cleaned, metrics


PROMPT_MAX_LEN = 500


def build_contextual_prompt(
    *,
    local_phrase: str,
    global_subject: str,
    art_direction: str,
    max_len: int = PROMPT_MAX_LEN,
) -> str:
    """Build an image prompt that stays within EditPlan overlay.prompt max length."""
    phrase = (local_phrase or "").strip()
    subject = (global_subject or "").strip() or "the speaker's topic"
    art = (art_direction or "").strip() or "clean modern social video, consistent palette"

    suffix = " No text in image, no logos, cinematic still."
    # Budget: keep phrase first, then art, then subject (most likely to bloat).
    # Leave room for wrappers + suffix.
    overhead = len('Illustration for: «». Art direction: . Subject: .') + len(suffix)
    budget = max(80, max_len - overhead)

    phrase_budget = min(len(phrase), max(40, budget // 2))
    phrase = phrase[:phrase_budget].rstrip()
    rest = budget - len(phrase)
    art_budget = min(len(art), max(20, rest // 2))
    art = art[:art_budget].rstrip()
    subject_budget = max(0, rest - len(art))
    subject = subject[:subject_budget].rstrip()

    prompt = (
        f"Illustration for: «{phrase}». "
        f"Art direction: {art}. "
        f"Subject: {subject}."
        f"{suffix}"
    )
    if len(prompt) > max_len:
        prompt = prompt[: max_len - 1].rstrip() + "…"
    return prompt

