"""Module 5 — zoom / effect scoring with budget + cooldown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from app.pipeline.timeline.event_schema import WordEvent, ZoomEvent, ZoomKind

ZoomKindT = ZoomKind

WINDOW_S = 0.5
DEFAULT_BUDGET_PER_MIN = 4.0
DEFAULT_COOLDOWN_S = 2.5


@dataclass(slots=True)
class ScoreWindow:
    start: float
    end: float
    score: float
    reasons: dict[str, float]


def _windows(duration: float, step: float = WINDOW_S) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    out: list[tuple[float, float]] = []
    t = 0.0
    while t < duration:
        out.append((t, min(duration, t + step)))
        t += step
    return out


def score_windows(
    *,
    duration: float,
    words: list[WordEvent],
    static_since: list[tuple[float, float]] | None = None,
) -> list[ScoreWindow]:
    """Composite score per 0.5s window (emphasis, speech rate, static holds)."""
    static = static_since or []
    windows: list[ScoreWindow] = []
    for start, end in _windows(duration):
        mid = (start + end) / 2
        reasons: dict[str, float] = {}
        emph = [w for w in words if w.start < end and w.end > start and w.important]
        if emph:
            reasons["emphasis"] = min(1.0, 0.45 + 0.15 * len(emph))
        rate_words = [w for w in words if w.start < end and w.end > start]
        rate = len(rate_words) / max(WINDOW_S, end - start)
        if rate >= 4.0:
            reasons["speech_rate"] = min(1.0, (rate - 3.0) / 4.0)
        # Micro-pause then emphasis: previous window sparse, current emph
        if emph:
            prev = [w for w in words if mid - 0.6 <= w.end <= mid - 0.15]
            if len(prev) <= 1:
                reasons["pause_punch"] = 0.55
        for s0, s1 in static:
            if s0 <= mid <= s1 and (s1 - s0) >= 4.0:
                reasons["static_hold"] = 0.4
                break
        score = 0.0
        if reasons:
            # Weighted blend, capped
            score = min(1.0, sum(reasons.values()) / max(1.0, len(reasons) * 0.85))
        windows.append(ScoreWindow(start=start, end=end, score=score, reasons=reasons))
    return windows


def local_maxima(windows: list[ScoreWindow], *, min_score: float = 0.35) -> list[ScoreWindow]:
    peaks: list[ScoreWindow] = []
    for i, w in enumerate(windows):
        if w.score < min_score:
            continue
        left = windows[i - 1].score if i > 0 else -1.0
        right = windows[i + 1].score if i + 1 < len(windows) else -1.0
        if w.score >= left and w.score >= right:
            peaks.append(w)
    return peaks


_KIND_CYCLE: list[ZoomKindT] = [
    "zoom_in_soft",
    "zoom_in_tight",
    "micro_pan",
    "zoom_out",
]


def apply_budget_cooldown(
    peaks: list[ScoreWindow],
    *,
    duration: float,
    budget_per_min: float = DEFAULT_BUDGET_PER_MIN,
    cooldown_s: float = DEFAULT_COOLDOWN_S,
    dry_run: bool = False,
) -> tuple[list[ZoomEvent], dict[str, Any]]:
    """Keep local maxima within budget/cooldown; vary kind consecutively."""
    max_effects = max(1, int(round((duration / 60.0) * budget_per_min)))
    ranked = sorted(peaks, key=lambda p: p.score, reverse=True)
    chosen: list[ScoreWindow] = []
    for peak in ranked:
        if len(chosen) >= max_effects:
            break
        if any(abs(peak.start - c.start) < cooldown_s for c in chosen):
            continue
        chosen.append(peak)
    chosen.sort(key=lambda p: p.start)

    events: list[ZoomEvent] = []
    last_kind: ZoomKindT | None = None
    kind_i = 0
    for peak in chosen:
        kind = _KIND_CYCLE[kind_i % len(_KIND_CYCLE)]
        if kind == last_kind:
            kind_i += 1
            kind = _KIND_CYCLE[kind_i % len(_KIND_CYCLE)]
        kind_i += 1
        last_kind = kind
        scale = {
            "zoom_in_tight": 1.28,
            "zoom_in_soft": 1.14,
            "zoom_out": 1.08,
            "micro_pan": 1.1,
        }[kind]
        dur = 1.1 if kind != "zoom_in_tight" else 0.85
        events.append(
            ZoomEvent(
                id=f"zoom-{uuid4().hex[:10]}",
                start=peak.start,
                end=min(duration, peak.start + dur),
                kind=kind,
                scale=scale,
                score=peak.score,
                important=True,
                meta={"reasons": peak.reasons, "dry_run": dry_run},
            )
        )

    metrics = {
        "peaks_found": len(peaks),
        "effects_placed": len(events),
        "budget_max": max_effects,
        "cooldown_s": cooldown_s,
        "budget_per_min": budget_per_min,
    }
    return events, metrics


def propose_zooms(
    *,
    duration: float,
    words: list[WordEvent],
    budget_per_min: float = DEFAULT_BUDGET_PER_MIN,
    cooldown_s: float = DEFAULT_COOLDOWN_S,
    dry_run: bool = False,
) -> tuple[list[ZoomEvent], dict[str, Any]]:
    windows = score_windows(duration=duration, words=words)
    peaks = local_maxima(windows)
    events, metrics = apply_budget_cooldown(
        peaks,
        duration=duration,
        budget_per_min=budget_per_min,
        cooldown_s=cooldown_s,
        dry_run=dry_run,
    )
    metrics["windows_scored"] = len(windows)
    return events, metrics
