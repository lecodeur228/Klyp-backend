"""Transcription provider factory."""

from app.analysis.providers.base import TranscriptionProvider
from app.analysis.providers.fake import FakeTranscriptionProvider
from app.analysis.providers.rodiumai_asr import RodiumAITranscriptionProvider
from app.analysis.providers.whisperx_asr import (
    WhisperXTranscriptionProvider,
    whisperx_available,
)
from app.core.config import Settings


def get_transcription_provider(settings: Settings) -> TranscriptionProvider:
    provider = settings.transcription_provider

    if provider == "fake":
        return FakeTranscriptionProvider()

    if provider == "rodiumai":
        return RodiumAITranscriptionProvider(settings)

    if provider == "whisperx":
        return WhisperXTranscriptionProvider(settings)

    # auto: prefer WhisperX when installed; else Rodium if AI live; else fake
    if provider == "auto":
        if whisperx_available():
            return WhisperXTranscriptionProvider(settings)
        if settings.ai_provider == "rodiumai" and settings.rodiumai_api_key:
            # Still use WhisperX wrapper for WAV extract + Rodium fallback path
            return WhisperXTranscriptionProvider(settings)
        return FakeTranscriptionProvider()

    return FakeTranscriptionProvider()
