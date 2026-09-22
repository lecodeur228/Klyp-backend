"""Deterministic silence + filler cuts → keep timeline segments.

Conservative by design: prefer leaving breath/tail audio rather than
clipping speech mid-phrase (ASR word/segment ends often arrive early).
"""

from __future__ import annotations

from typing import Any

from app.schemas.editplan import TimelineSegment

# Only remove pauses that feel like real dead air (not thinking breaths).
MIN_SILENCE_S = 0.85
# Never cut flush against speech — keep a tail/lead so syllables finish.
EDGE_PAD_S = 0.25
FILLER_PAD_S = 0.02
MIN_KEEP_S = 0.35
MIN_CUT_S = 0.35


def _clamp(t: float, total: float) -> float:
    return max(0.0, min(float(t), total))


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda x: x[0])
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e + 0.05:
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged


def _speech_points(
    segments: list[dict[str, Any]] | None,
    *,
    prefer_words: bool = True,
) -> list[tuple[float, float]]:
    """Collect speech spans.

    When word-level timestamps exist (WhisperX align), use words for finer
    silence detection. Otherwise fall back to segment bounds (safer than
    interpolated fake words).
    """
    word_points: list[tuple[float, float]] = []
    seg_points: list[tuple[float, float]] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        try:
            ss = float(seg.get("start", 0))
            se = float(seg.get("end", ss))
        except (TypeError, ValueError):
            continue
        if se > ss:
            seg_points.append((ss, se))
        words = seg.get("words")
        if prefer_words and isinstance(words, list):
            for w in words:
                if not isinstance(w, dict):
                    continue
                try:
                    ws = float(w.get("start", 0))
                    we = float(w.get("end", ws))
                except (TypeError, ValueError):
                    continue
                if we > ws:
                    word_points.append((ws, we))
    if word_points and len(word_points) >= max(2, len(seg_points)):
        return sorted(word_points, key=lambda x: x[0])
    return sorted(seg_points, key=lambda x: x[0])


def _gap_silences(
    speech: list[tuple[float, float]],
    *,
    duration: float,
    min_silence: float = MIN_SILENCE_S,
    edge_pad: float = EDGE_PAD_S,
) -> list[tuple[float, float]]:
    """Cut only the *interior* of long gaps, leaving pad against speech."""
    if not speech:
        return []
    gaps: list[tuple[float, float]] = []

    first_start = speech[0][0]
    if first_start >= min_silence:
        cut_end = max(0.0, first_start - edge_pad)
        if cut_end >= MIN_CUT_S:
            gaps.append((0.0, cut_end))

    for i in range(len(speech) - 1):
        gap_start = speech[i][1]
        gap_end = speech[i + 1][0]
        if gap_end - gap_start < min_silence:
            continue
        cut_start = gap_start + edge_pad
        cut_end = gap_end - edge_pad
        if cut_end - cut_start >= MIN_CUT_S:
            gaps.append((cut_start, cut_end))

    last_end = speech[-1][1]
    if duration - last_end >= min_silence:
        cut_start = min(duration, last_end + edge_pad)
        if duration - cut_start >= MIN_CUT_S:
            gaps.append((cut_start, duration))
    return gaps


def _vad_silences(
    vad_segments: list[dict[str, Any]] | None,
    *,
    duration: float,
    edge_pad: float = EDGE_PAD_S,
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s in vad_segments or []:
        if not isinstance(s, dict):
            continue
        if s.get("kind", "silence") != "silence":
            continue
        try:
            start = _clamp(float(s["start"]), duration)
            end = _clamp(float(s["end"]), duration)
        except (KeyError, TypeError, ValueError):
            continue
        # Shrink VAD silence so we keep audio at speech boundaries
        cut_start = start + edge_pad
        cut_end = end - edge_pad
        if cut_end - cut_start >= MIN_CUT_S and cut_end - cut_start >= MIN_SILENCE_S * 0.6:
            out.append((cut_start, cut_end))
    return out


def _filler_cuts(
    fillers: list[dict[str, Any]] | None,
    *,
    duration: float,
    pad: float = FILLER_PAD_S,
) -> list[tuple[float, float]]:
    """Remove short fillers only — tiny pad so we don't eat neighboring syllables."""
    out: list[tuple[float, float]] = []
    for f in fillers or []:
        if not isinstance(f, dict):
            continue
        try:
            raw_start = float(f["start"])
            raw_end = float(f["end"])
        except (KeyError, TypeError, ValueError):
            continue
        # Skip tiny / uncertain filler spans (often bad estimates mid-word)
        if raw_end - raw_start < 0.12:
            continue
        start = _clamp(raw_start - pad, duration)
        end = _clamp(raw_end + pad, duration)
        if end - start >= 0.12:
            out.append((start, end))
    return out


def build_cut_ranges(
    *,
    duration: float,
    segments: list[dict[str, Any]] | None = None,
    vad_segments: list[dict[str, Any]] | None = None,
    fillers: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float]]:
    """Merged ranges to remove (silence + fillers)."""
    total = duration if duration and duration > 0 else 0.1
    cuts: list[tuple[float, float]] = []
    vad = _vad_silences(vad_segments, duration=total)
    if vad:
        cuts.extend(vad)
    else:
        speech = _speech_points(segments)
        cuts.extend(_gap_silences(speech, duration=total))
    cuts.extend(_filler_cuts(fillers, duration=total))
    return _merge_ranges(cuts)


def keep_ranges_from_cuts(
    cuts: list[tuple[float, float]],
    *,
    duration: float,
    min_keep: float = MIN_KEEP_S,
) -> list[tuple[float, float]]:
    total = duration if duration and duration > 0 else 0.1
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in cuts:
        start = _clamp(start, total)
        end = _clamp(end, total)
        if start > cursor + 0.01:
            keeps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total - 0.01:
        keeps.append((cursor, total))
    filtered = [(a, b) for a, b in keeps if b - a >= min_keep]
    return filtered or [(0.0, total)]


def _expand_keeps(
    keeps: list[tuple[float, float]],
    *,
    duration: float,
    pad: float = EDGE_PAD_S,
) -> list[tuple[float, float]]:
    """Final safety: grow each keep slightly so phrase tails aren't clipped."""
    if not keeps:
        return [(0.0, duration)]
    expanded = [
        (_clamp(a - pad * 0.4, duration), _clamp(b + pad, duration))
        for a, b in keeps
    ]
    return _merge_ranges(expanded) or [(0.0, duration)]


def build_keep_segments(
    *,
    duration: float,
    segments: list[dict[str, Any]] | None = None,
    vad_segments: list[dict[str, Any]] | None = None,
    fillers: list[dict[str, Any]] | None = None,
) -> list[TimelineSegment]:
    cuts = build_cut_ranges(
        duration=duration,
        segments=segments,
        vad_segments=vad_segments,
        fillers=fillers,
    )
    keeps = keep_ranges_from_cuts(cuts, duration=duration)
    keeps = _expand_keeps(keeps, duration=duration)
    return [
        TimelineSegment(id=f"keep-{i + 1}", start=round(a, 3), end=round(b, 3))
        for i, (a, b) in enumerate(keeps)
    ]


def source_to_output(t: float, keeps: list[tuple[float, float]]) -> float | None:
    """Map source time to edited timeline; None if inside a cut."""
    offset = 0.0
    for a, b in keeps:
        if t < a:
            return None
        if a <= t <= b:
            return offset + (t - a)
        offset += b - a
    return None


def output_to_source(t: float, keeps: list[tuple[float, float]]) -> float:
    """Map edited timeline time to source time."""
    remaining = max(0.0, t)
    for a, b in keeps:
        length = b - a
        if remaining <= length:
            return a + remaining
        remaining -= length
    if keeps:
        return keeps[-1][1]
    return t


def remap_interval(
    start: float,
    end: float,
    keeps: list[tuple[float, float]],
) -> tuple[float, float] | None:
    """Remap [start, end] from source to output clock; None if fully cut."""
    out_start = source_to_output(start, keeps)
    out_end = source_to_output(end, keeps)
    if out_start is None:
        for a, b in keeps:
            if start < a < end:
                out_start = source_to_output(a, keeps)
                break
    if out_end is None:
        for a, b in reversed(keeps):
            if start < b < end:
                out_end = source_to_output(b, keeps)
                break
    if out_start is None or out_end is None:
        return None
    if out_end <= out_start:
        return None
    return (round(out_start, 3), round(out_end, 3))


def edited_duration(keeps: list[tuple[float, float]]) -> float:
    return round(sum(b - a for a, b in keeps), 3)


def keep_tuples(segments: list[TimelineSegment] | list[dict[str, Any]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s in segments:
        if isinstance(s, dict):
            try:
                a, b = float(s["start"]), float(s["end"])
            except (KeyError, TypeError, ValueError):
                continue
        else:
            a, b = float(s.start), float(s.end)
        if b > a:
            out.append((a, b))
    return out
