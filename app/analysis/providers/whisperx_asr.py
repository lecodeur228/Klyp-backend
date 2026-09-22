"""WhisperX transcription + forced alignment (word-level timestamps).

Optional heavy deps (torch / whisperx). Falls back to RodiumAI ASR when
WhisperX is unavailable or fails — still extracts 16 kHz WAV first when possible.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analysis.audio_extract import download_media, extract_wav_16k, ffmpeg_available
from app.analysis.providers.base import (
    TranscriptResult,
    TranscriptSegmentResult,
    TranscriptWordResult,
)
from app.analysis.providers.rodiumai_asr import (
    FILLERS,
    RodiumAITranscriptionProvider,
    cloudinary_audio_url,
)
from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import AIProviderException

logger = logging.getLogger(__name__)

# Cached whisperx models (process lifetime)
_WX_MODEL = None
_WX_ALIGN: dict[str, tuple] = {}
_WX_DEVICE: str | None = None


def whisperx_available() -> bool:
    try:
        import whisperx  # noqa: F401
        import torch  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _device_and_compute() -> tuple[str, str]:
    import torch

    if torch.cuda.is_available():
        return "cuda", "float16"
    # Apple Silicon
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "cpu", "int8"  # whisperx align more stable on cpu int8
    return "cpu", "int8"


def _load_whisperx_model(settings: Settings):
    global _WX_MODEL, _WX_DEVICE
    import whisperx

    if _WX_MODEL is not None:
        return _WX_MODEL
    device, compute = _device_and_compute()
    _WX_DEVICE = device
    model_name = settings.whisperx_model
    logger.info("Loading WhisperX model=%s device=%s compute=%s", model_name, device, compute)
    _WX_MODEL = whisperx.load_model(model_name, device, compute_type=compute)
    return _WX_MODEL


def _align_segments(
    segments: list[dict],
    *,
    audio,
    language: str,
    device: str,
) -> list[dict]:
    import whisperx

    if language not in _WX_ALIGN:
        model_a, metadata = whisperx.load_align_model(language_code=language, device=device)
        _WX_ALIGN[language] = (model_a, metadata)
    model_a, metadata = _WX_ALIGN[language]
    aligned = whisperx.align(
        segments,
        model_a,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )
    return list(aligned.get("segments") or segments)


def _fillers_from_words(words: list[TranscriptWordResult]) -> list[dict]:
    out: list[dict] = []
    for w in words:
        normalized = w.word.lower().strip(".,!?;:'\"…")
        if normalized in FILLERS:
            out.append({"word": w.word, "start": w.start, "end": w.end})
    return out


def _vad_from_words(
    words: list[TranscriptWordResult],
    *,
    duration: float,
    min_gap: float = 0.45,
) -> list[dict]:
    """Silence ranges as complement of word spans (for cut/QA)."""
    if not words:
        return []
    total = duration if duration > 0 else max(words[-1].end, 0.1)
    speech = sorted((w.start, w.end) for w in words if w.end > w.start)
    gaps: list[dict] = []
    cursor = 0.0
    for start, end in speech:
        if start - cursor >= min_gap:
            gaps.append({"start": round(cursor, 3), "end": round(start, 3), "kind": "silence"})
        cursor = max(cursor, end)
    if total - cursor >= min_gap:
        gaps.append({"start": round(cursor, 3), "end": round(total, 3), "kind": "silence"})
    return gaps


def _qa_warning(
    words: list[TranscriptWordResult],
    vad: list[dict],
    *,
    duration: float,
    threshold: float = 0.3,
) -> str | None:
    if not words:
        return "no_word_timestamps"
    word_span = sum(max(0.0, w.end - w.start) for w in words)
    speech_via_vad = duration
    for s in vad:
        if s.get("kind") == "silence":
            speech_via_vad -= max(0.0, float(s["end"]) - float(s["start"]))
    speech_via_vad = max(0.0, speech_via_vad)
    # Prefer comparing word coverage to non-silence duration
    delta = abs(word_span - speech_via_vad)
    if speech_via_vad > 0.5 and delta > threshold and delta / max(speech_via_vad, 0.1) > 0.25:
        return f"word_timing_drift:{delta:.3f}s"
    first, last = words[0].start, words[-1].end
    if duration > 1 and (first > 2.0 or duration - last > 3.0):
        # loose check only
        pass
    return None


def _segments_from_whisperx(
    raw_segments: list[dict],
    *,
    duration: float,
) -> tuple[list[TranscriptSegmentResult], list[TranscriptWordResult]]:
    segments: list[TranscriptSegmentResult] = []
    all_words: list[TranscriptWordResult] = []
    for i, seg in enumerate(raw_segments):
        text = str(seg.get("text") or "").strip()
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 0.15
        words_out: list[TranscriptWordResult] = []
        for w in seg.get("words") or []:
            if not isinstance(w, dict):
                continue
            token = str(w.get("word") or w.get("text") or "").strip()
            if not token:
                continue
            try:
                ws = float(w.get("start", start))
                we = float(w.get("end", ws))
            except (TypeError, ValueError):
                continue
            if we <= ws:
                we = ws + 0.05
            tw = TranscriptWordResult(word=token, start=round(ws, 3), end=round(we, 3))
            words_out.append(tw)
            all_words.append(tw)
        if not words_out and text:
            # Fallback: keep segment without fake word splits
            words_out = []
        segments.append(
            TranscriptSegmentResult(
                id=f"seg-{i + 1}",
                start=round(start, 3),
                end=round(end, 3),
                text=text or " ".join(w.word for w in words_out),
                words=words_out,
            )
        )
    return segments, all_words


class WhisperXTranscriptionProvider:
    """Clean ASR: 16 kHz WAV → WhisperX align → real word timestamps."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _prepare_wav(self, media_url: str) -> tuple[Path, Path | None]:
        """Return (wav_path, downloaded_source_or_None)."""
        url = cloudinary_audio_url(media_url)
        downloaded: Path | None = None
        source: Path
        if url.startswith("http"):
            downloaded = download_media(
                url, timeout=max(180.0, float(self.settings.rodiumai_timeout) * 4)
            )
            source = downloaded
        else:
            source = Path(url)
        if not ffmpeg_available():
            return source, downloaded
        wav = extract_wav_16k(source)
        return wav, downloaded

    def _run_whisperx(self, wav_path: Path, *, language: str, duration: float) -> TranscriptResult:
        import whisperx

        device, _ = _device_and_compute()
        model = _load_whisperx_model(self.settings)
        audio = whisperx.load_audio(str(wav_path))
        result = model.transcribe(audio, language=language, batch_size=8)
        lang = str(result.get("language") or language)
        raw_segs = list(result.get("segments") or [])
        if raw_segs:
            raw_segs = _align_segments(raw_segs, audio=audio, language=lang[:2], device=device)
        segments, all_words = _segments_from_whisperx(raw_segs, duration=duration)
        fillers = _fillers_from_words(all_words)
        vad = _vad_from_words(all_words, duration=duration)
        warning = _qa_warning(all_words, vad, duration=duration)
        return TranscriptResult(
            language=lang[:8],
            segments=segments,
            vad_segments=vad,
            fillers=fillers,
            quality_warning=warning,
            aligned=True,
        )

    def transcribe(
        self,
        *,
        duration: float,
        language: str | None = None,
        media_url: str | None = None,
    ) -> TranscriptResult:
        lang = (language or "fr")[:2]
        if not media_url:
            raise AIProviderException(
                "Media URL required for WhisperX transcription",
                code=ErrorCode.AI_INVALID_RESPONSE,
            )

        wav_path: Path | None = None
        downloaded: Path | None = None
        try:
            try:
                wav_path, downloaded = self._prepare_wav(media_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("WAV extract failed (%s) — fallback without clean extract", exc)

            if whisperx_available() and wav_path is not None:
                try:
                    return self._run_whisperx(wav_path, language=lang, duration=duration)
                except Exception:  # noqa: BLE001
                    logger.exception("WhisperX failed — falling back to RodiumAI ASR")

            provider = RodiumAITranscriptionProvider(self.settings)
            result = provider.transcribe(
                duration=duration, language=language, media_url=media_url
            )
            all_words = [w for s in result.segments for w in s.words]
            return TranscriptResult(
                language=result.language,
                segments=result.segments,
                vad_segments=result.vad_segments
                or _vad_from_words(all_words, duration=duration),
                fillers=result.fillers,
                quality_warning=result.quality_warning
                or "whisperx_unavailable_fallback_rodium",
                aligned=False,
            )
        finally:
            for path in (wav_path, downloaded):
                if path is None:
                    continue
                try:
                    # Only delete temps we created (wav always; downloaded if remote)
                    if path.suffix == ".wav" or downloaded is path:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
