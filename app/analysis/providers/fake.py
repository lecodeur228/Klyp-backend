"""Deterministic fake ASR for Sprint C / tests."""

from __future__ import annotations

from app.analysis.providers.base import (
    TranscriptResult,
    TranscriptSegmentResult,
    TranscriptWordResult,
)

DEFAULT_DURATION = 30.0

# Phrases include fillers for stub detection
_PHRASES = (
    "Bonjour et bienvenue sur Klyp",
    "Euh aujourd'hui on va éditer cette vidéo",
    "Um c'est parti pour le montage",
)


class FakeTranscriptionProvider:
    def transcribe(
        self,
        *,
        duration: float,
        language: str | None = None,
        media_url: str | None = None,
    ) -> TranscriptResult:
        total = duration if duration and duration > 0 else DEFAULT_DURATION
        lang = language or "fr"
        _ = media_url
        n = len(_PHRASES)
        slot = total / n
        segments: list[TranscriptSegmentResult] = []
        fillers: list[dict] = []
        vad_segments: list[dict] = []

        for i, phrase in enumerate(_PHRASES):
            seg_start = round(i * slot, 3)
            seg_end = round((i + 1) * slot - 0.15, 3) if i < n - 1 else round(total, 3)
            if seg_end <= seg_start:
                seg_end = round(seg_start + 0.5, 3)

            words_raw = phrase.split()
            word_slot = (seg_end - seg_start) / max(len(words_raw), 1)
            words: list[TranscriptWordResult] = []
            for j, token in enumerate(words_raw):
                w_start = round(seg_start + j * word_slot, 3)
                w_end = round(seg_start + (j + 1) * word_slot, 3)
                words.append(TranscriptWordResult(word=token, start=w_start, end=w_end))
                normalized = token.lower().strip(".,!?'\"")
                if normalized in {"euh", "um", "uh", "hum"}:
                    fillers.append({"word": token, "start": w_start, "end": w_end})

            segments.append(
                TranscriptSegmentResult(
                    id=f"seg-{i + 1}",
                    start=seg_start,
                    end=seg_end,
                    text=phrase,
                    words=words,
                )
            )

            if i < n - 1:
                gap_start = seg_end
                gap_end = round((i + 1) * slot, 3)
                if gap_end > gap_start:
                    vad_segments.append(
                        {"start": gap_start, "end": gap_end, "kind": "silence"}
                    )

        return TranscriptResult(
            language=lang,
            segments=segments,
            vad_segments=vad_segments,
            fillers=fillers,
            quality_warning=None,
            aligned=True,
        )
