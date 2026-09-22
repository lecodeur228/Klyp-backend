"""Build caption cues from analysis transcript segments."""

from __future__ import annotations

from typing import Any, Literal

CaptionStyle = Literal["minimal", "dynamic"]

DYNAMIC_WORDS_PER_CUE = 5


def build_cues(
    segments: list[dict[str, Any]] | None,
    style: CaptionStyle = "minimal",
) -> list[dict[str, Any]]:
    """Derive timed caption cues from transcript segments."""
    segs = list(segments or [])
    if style == "dynamic":
        return _build_dynamic(segs)
    return _build_minimal(segs)


def _build_minimal(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        words = list(seg.get("words") or [])
        cues.append(
            {
                "id": str(seg.get("id") or f"cue-{i + 1}"),
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", 0)),
                "text": str(seg.get("text") or "").strip(),
                "words": [
                    {
                        "word": str(w.get("word", "")),
                        "start": float(w.get("start", 0)),
                        "end": float(w.get("end", 0)),
                    }
                    for w in words
                ],
            }
        )
    return cues


def _build_dynamic(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split into shorter cues (~DYNAMIC_WORDS_PER_CUE words) for highlight UI."""
    cues: list[dict[str, Any]] = []
    cue_idx = 0
    for seg in segments:
        words = list(seg.get("words") or [])
        if not words:
            cue_idx += 1
            cues.append(
                {
                    "id": f"cue-{cue_idx}",
                    "start": float(seg.get("start", 0)),
                    "end": float(seg.get("end", 0)),
                    "text": str(seg.get("text") or "").strip(),
                    "words": [],
                }
            )
            continue

        for offset in range(0, len(words), DYNAMIC_WORDS_PER_CUE):
            chunk = words[offset : offset + DYNAMIC_WORDS_PER_CUE]
            cue_idx += 1
            cues.append(
                {
                    "id": f"cue-{cue_idx}",
                    "start": float(chunk[0].get("start", 0)),
                    "end": float(chunk[-1].get("end", 0)),
                    "text": " ".join(str(w.get("word", "")) for w in chunk).strip(),
                    "words": [
                        {
                            "word": str(w.get("word", "")),
                            "start": float(w.get("start", 0)),
                            "end": float(w.get("end", 0)),
                        }
                        for w in chunk
                    ],
                }
            )
    return cues


def validate_cues_monotonic(cues: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return field errors if cues have invalid / overlapping timestamps."""
    errors: dict[str, list[str]] = {}
    prev_end = -1.0
    for i, cue in enumerate(cues):
        key = f"cues[{i}]"
        start = float(cue.get("start", 0))
        end = float(cue.get("end", 0))
        if end < start:
            errors.setdefault(key, []).append("end must be >= start")
        if start < prev_end - 1e-6:
            errors.setdefault(key, []).append("overlapping or out-of-order cues")
        prev_end = max(prev_end, end)
    return errors
