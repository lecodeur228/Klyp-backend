"""RodiumAI audio transcription (real ASR from uploaded media)."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

from app.analysis.providers.base import (
    TranscriptResult,
    TranscriptSegmentResult,
    TranscriptWordResult,
)
from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import AIProviderException, AITimeoutException

logger = logging.getLogger(__name__)

FILLERS = {"euh", "um", "uh", "hum", "hmm", "ah", "bah"}
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…])(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ])")
COMMA_SPLIT = re.compile(r",\s+")


def cloudinary_audio_url(secure_url: str) -> str:
    """Insert `f_mp3` transform so Cloudinary returns audio-only for ASR."""
    marker = "/upload/"
    if "res.cloudinary.com" in secure_url and marker in secure_url:
        head, tail = secure_url.split(marker, 1)
        if not tail.startswith("f_"):
            return f"{head}{marker}f_mp3/{tail}"
    return secure_url


def _words_in_span(
    phrase: str,
    *,
    seg_start: float,
    seg_end: float,
) -> tuple[list[TranscriptWordResult], list[dict]]:
    tokens = phrase.split()
    words: list[TranscriptWordResult] = []
    fillers: list[dict] = []
    if not tokens:
        return words, fillers
    span = max(seg_end - seg_start, 0.05)
    token_weights = [max(len(t), 1) for t in tokens]
    token_sum = float(sum(token_weights))
    w_cursor = seg_start
    for j, token in enumerate(tokens):
        w_span = span * (token_weights[j] / token_sum)
        w_start = round(w_cursor, 3)
        w_end = round(seg_end if j == len(tokens) - 1 else w_cursor + w_span, 3)
        if w_end <= w_start:
            w_end = round(w_start + 0.05, 3)
        words.append(TranscriptWordResult(word=token, start=w_start, end=w_end))
        normalized = token.lower().strip(".,!?;:'\"…")
        if normalized in FILLERS:
            fillers.append({"word": token, "start": w_start, "end": w_end})
        w_cursor = w_end
    return words, fillers


def _chunk_by_words(text: str, *, max_words: int = 12) -> list[str]:
    tokens = text.split()
    if len(tokens) <= max_words:
        return [text] if text else []
    return [
        " ".join(tokens[i : i + max_words]) for i in range(0, len(tokens), max_words)
    ]


def _split_phrases(text: str) -> list[str]:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return []
    raw_parts = [p.strip() for p in SENTENCE_SPLIT.split(cleaned) if p and p.strip()]
    if not raw_parts:
        raw_parts = [cleaned]

    parts: list[str] = []
    for part in raw_parts:
        if len(part.split()) <= 16:
            parts.append(part)
            continue
        # Prefer comma breaks (keeps words intact), then hard word chunks
        clauses = [c.strip() for c in COMMA_SPLIT.split(part) if c and c.strip()]
        if len(clauses) > 1:
            for clause in clauses:
                parts.extend(_chunk_by_words(clause, max_words=14))
        else:
            parts.extend(_chunk_by_words(part, max_words=12))

    merged: list[str] = []
    for part in parts:
        if merged and len(part.split()) < 3:
            merged[-1] = f"{merged[-1]} {part}".strip()
        elif merged and len(merged[-1].split()) < 3:
            merged[-1] = f"{merged[-1]} {part}".strip()
        else:
            merged.append(part)
    return merged or [cleaned]


def _estimate_timed_result(
    text: str,
    *,
    duration: float,
    language: str,
) -> TranscriptResult:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return TranscriptResult(language=language, segments=[], vad_segments=[], fillers=[])

    total = duration if duration and duration > 0 else 30.0
    raw_parts = _split_phrases(cleaned)
    weights = [max(len(p), 1) for p in raw_parts]
    weight_sum = float(sum(weights))
    segments: list[TranscriptSegmentResult] = []
    fillers: list[dict] = []
    cursor = 0.0

    for i, phrase in enumerate(raw_parts):
        span = total * (weights[i] / weight_sum)
        seg_start = round(cursor, 3)
        seg_end = round(total if i == len(raw_parts) - 1 else cursor + span, 3)
        if seg_end <= seg_start:
            seg_end = round(seg_start + 0.2, 3)
        words, seg_fillers = _words_in_span(phrase, seg_start=seg_start, seg_end=seg_end)
        fillers.extend(seg_fillers)
        segments.append(
            TranscriptSegmentResult(
                id=f"seg-{i + 1}",
                start=seg_start,
                end=seg_end,
                text=phrase,
                words=words,
            )
        )
        cursor = seg_end

    return TranscriptResult(
        language=language,
        segments=segments,
        vad_segments=[],
        fillers=fillers,
    )


def _from_diarized_payload(payload: dict, *, language: str, duration: float) -> TranscriptResult | None:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None

    segments: list[TranscriptSegmentResult] = []
    fillers: list[dict] = []
    for i, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            seg_start = float(item.get("start", 0))
            seg_end = float(item.get("end", seg_start))
        except (TypeError, ValueError):
            continue
        if seg_end <= seg_start:
            seg_end = seg_start + 0.2

        # Subdivide long timed segments so captions stay close to speech pace
        phrases = _split_phrases(text)
        if len(phrases) <= 1:
            words, seg_fillers = _words_in_span(text, seg_start=seg_start, seg_end=seg_end)
            fillers.extend(seg_fillers)
            segments.append(
                TranscriptSegmentResult(
                    id=str(item.get("id") or f"seg-{i + 1}"),
                    start=round(seg_start, 3),
                    end=round(seg_end, 3),
                    text=text,
                    words=words,
                )
            )
            continue

        weights = [max(len(p), 1) for p in phrases]
        weight_sum = float(sum(weights))
        span = seg_end - seg_start
        cursor = seg_start
        for j, phrase in enumerate(phrases):
            part_span = span * (weights[j] / weight_sum)
            p_start = round(cursor, 3)
            p_end = round(seg_end if j == len(phrases) - 1 else cursor + part_span, 3)
            if p_end <= p_start:
                p_end = round(p_start + 0.15, 3)
            words, seg_fillers = _words_in_span(phrase, seg_start=p_start, seg_end=p_end)
            fillers.extend(seg_fillers)
            segments.append(
                TranscriptSegmentResult(
                    id=f"{item.get('id') or f'seg-{i + 1}'}-{j + 1}",
                    start=p_start,
                    end=p_end,
                    text=phrase,
                    words=words,
                )
            )
            cursor = p_end

    if not segments:
        return None

    detected = language
    if payload.get("language"):
        detected = str(payload["language"])
    # Prefer model-reported audio duration when present
    _ = duration
    return TranscriptResult(
        language=detected,
        segments=segments,
        vad_segments=[],
        fillers=fillers,
    )


class RodiumAITranscriptionProvider:
    """Download media audio and transcribe via RodiumAI OpenAI-compatible ASR."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _post_transcription(
        self,
        *,
        client: httpx.Client,
        content: bytes,
        filename: str,
        mime: str,
        model: str,
        lang: str,
        response_format: str,
        extra: dict[str, str] | None = None,
    ) -> httpx.Response:
        data: dict[str, str] = {
            "model": model,
            "response_format": response_format,
            "language": lang,
        }
        if extra:
            data.update(extra)
        files = {"file": (filename, content, mime)}
        return client.post(
            f"{self.settings.rodiumai_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.settings.rodiumai_api_key}"},
            data=data,
            files=files,
        )

    def transcribe(
        self,
        *,
        duration: float,
        language: str | None = None,
        media_url: str | None = None,
    ) -> TranscriptResult:
        lang = language or "fr"
        if not media_url:
            raise AIProviderException(
                "Media URL required for real transcription",
                code=ErrorCode.AI_INVALID_RESPONSE,
            )
        if not self.settings.rodiumai_api_key:
            raise AIProviderException(
                "RODIUMAI_API_KEY missing",
                code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
            )

        audio_url = cloudinary_audio_url(media_url)
        timeout = max(180.0, float(self.settings.rodiumai_timeout) * 4)
        model = self.settings.transcription_model

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                media_resp = client.get(audio_url)
                media_resp.raise_for_status()
                content = media_resp.content
                content_type = media_resp.headers.get("content-type", "audio/mpeg")

                path = urlparse(audio_url).path.lower()
                if path.endswith(".mp3") or "audio" in content_type:
                    filename = "audio.mp3"
                    mime = "audio/mpeg"
                elif path.endswith(".wav"):
                    filename = "audio.wav"
                    mime = "audio/wav"
                elif path.endswith(".mov"):
                    filename = "video.mov"
                    mime = "video/quicktime"
                elif path.endswith(".webm"):
                    filename = "video.webm"
                    mime = "video/webm"
                else:
                    filename = "video.mp4"
                    mime = "video/mp4"

                # Prefer diarized_json when the model supports it (real segment times)
                use_diarize = "diarize" in model.lower()
                if use_diarize:
                    asr_resp = self._post_transcription(
                        client=client,
                        content=content,
                        filename=filename,
                        mime=mime,
                        model=model,
                        lang=lang,
                        response_format="diarized_json",
                        extra={"chunking_strategy": "auto"},
                    )
                    # Fallback if gateway rejects diarized_json
                    if asr_resp.status_code >= 400:
                        logger.warning(
                            "diarized_json failed status=%s body=%s — falling back to json",
                            asr_resp.status_code,
                            asr_resp.text[:200],
                        )
                        asr_resp = self._post_transcription(
                            client=client,
                            content=content,
                            filename=filename,
                            mime=mime,
                            model=model,
                            lang=lang,
                            response_format="json",
                        )
                else:
                    asr_resp = self._post_transcription(
                        client=client,
                        content=content,
                        filename=filename,
                        mime=mime,
                        model=model,
                        lang=lang,
                        response_format="json",
                    )
        except httpx.TimeoutException as exc:
            raise AITimeoutException() from exc
        except httpx.HTTPError as exc:
            raise AIProviderException(
                "Failed to download or transcribe media",
                code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
            ) from exc

        if asr_resp.status_code >= 400:
            raise AIProviderException(
                asr_resp.text[:300] or "Transcription failed",
                code=ErrorCode.AI_INVALID_RESPONSE,
                status_code=502,
            )

        payload = asr_resp.json()
        if not isinstance(payload, dict):
            raise AIProviderException(
                "Invalid transcription payload",
                code=ErrorCode.AI_INVALID_RESPONSE,
            )

        timed = _from_diarized_payload(payload, language=lang, duration=duration)
        if timed is not None:
            logger.info(
                "ASR diarized ok model=%s segments=%s duration=%s",
                model,
                len(timed.segments),
                duration,
            )
            return timed

        text = str(payload.get("text") or "").strip()
        if not text:
            raise AIProviderException(
                "Empty transcription",
                code=ErrorCode.AI_INVALID_RESPONSE,
            )

        detected = lang
        if payload.get("language"):
            detected = str(payload["language"])

        logger.info(
            "ASR estimated ok model=%s chars=%s duration=%s",
            model,
            len(text),
            duration,
        )
        return _estimate_timed_result(text, duration=duration, language=detected)
