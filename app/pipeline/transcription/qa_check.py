"""Module 1 — transcription QA helpers (dry-run metrics, needs_review)."""

from __future__ import annotations

from typing import Any


QA_DRIFT_THRESHOLD_S = 0.3


def speech_coverage_seconds(vad_segments: list[dict[str, Any]] | None) -> float:
    total = 0.0
    for seg in vad_segments or []:
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or start)
        total += max(0.0, end - start)
    return total


def words_coverage_seconds(segments: list[dict[str, Any]] | None) -> float:
    spans: list[tuple[float, float]] = []
    for seg in segments or []:
        words = seg.get("words") or []
        if words:
            for w in words:
                start = float(w.get("start") or 0)
                end = float(w.get("end") or start)
                if end > start:
                    spans.append((start, end))
        else:
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or start)
            if end > start:
                spans.append((start, end))
    if not spans:
        return 0.0
    spans.sort()
    merged: list[list[float]] = [[spans[0][0], spans[0][1]]]
    for start, end in spans[1:]:
        if start <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(e - s for s, e in merged)


def evaluate_sync_qa(
    *,
    vad_segments: list[dict[str, Any]] | None,
    segments: list[dict[str, Any]] | None,
    aligned: bool,
    quality_warning: str | None = None,
    threshold_s: float = QA_DRIFT_THRESHOLD_S,
) -> dict[str, Any]:
    """Compare VAD speech duration vs transcribed word coverage.

    If absolute drift exceeds ``threshold_s``, mark needs_review.
    """
    vad_s = speech_coverage_seconds(vad_segments)
    word_s = words_coverage_seconds(segments)
    drift = abs(vad_s - word_s)
    # When VAD is empty (Rodium path), fall back to quality_warning / aligned flag
    if vad_s <= 0 and word_s > 0:
        needs_review = bool(quality_warning) or not aligned
        return {
            "vad_speech_s": vad_s,
            "word_coverage_s": word_s,
            "drift_s": 0.0,
            "threshold_s": threshold_s,
            "needs_review": needs_review,
            "aligned": aligned,
            "quality_warning": quality_warning,
            "note": "vad_empty_skipped_drift",
        }

    needs_review = drift > threshold_s
    if quality_warning:
        needs_review = True
    return {
        "vad_speech_s": round(vad_s, 3),
        "word_coverage_s": round(word_s, 3),
        "drift_s": round(drift, 3),
        "threshold_s": threshold_s,
        "needs_review": needs_review,
        "aligned": aligned,
        "quality_warning": quality_warning,
    }
