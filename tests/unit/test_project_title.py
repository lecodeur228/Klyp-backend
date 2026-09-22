"""Tests for smart project titles from transcript."""

from __future__ import annotations

from app.services.projects.title_from_transcript import (
    looks_like_default_title,
    title_from_transcript_segments,
)


def test_looks_like_default_filename():
    assert looks_like_default_title("IMG_4521")
    assert looks_like_default_title("my-vacation-clip")
    assert looks_like_default_title("video.mp4")
    assert looks_like_default_title("Nouvelle vidéo")
    assert looks_like_default_title("Untitled video")
    assert not looks_like_default_title("Pourquoi tu dois arrêter ça")


def test_title_prefers_strong_first_sentence():
    segments = [
        {
            "id": "1",
            "start": 0,
            "end": 3,
            "text": "Aujourd'hui je te montre le secret pour poster tous les jours.",
        },
        {"id": "2", "start": 3, "end": 6, "text": "Euh voilà ok."},
    ]
    title = title_from_transcript_segments(segments)
    assert title is not None
    assert "secret" in title.lower() or "montre" in title.lower()


def test_title_picks_hook_over_weak_opener():
    segments = [
        {"id": "1", "start": 0, "end": 1, "text": "Euh bonjour."},
        {
            "id": "2",
            "start": 1,
            "end": 4,
            "text": "Voici l'astuce que personne n'utilise pour gagner du temps.",
        },
    ]
    title = title_from_transcript_segments(segments)
    assert title is not None
    assert "astuce" in title.lower() or "temps" in title.lower()


def test_title_truncates_long_sentence():
    long = " ".join(["mot"] * 40) + "."
    title = title_from_transcript_segments(
        [{"id": "1", "start": 0, "end": 5, "text": long}]
    )
    assert title is not None
    assert len(title) <= 73
