"""Derive a human project title from ASR transcript text."""

from __future__ import annotations

import re
from typing import Any

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9']+")
_FILLER_ONLY = frozenset(
    {
        "euh",
        "heu",
        "hum",
        "hmm",
        "ben",
        "bah",
        "voilà",
        "voila",
        "ok",
        "okay",
        "oui",
        "non",
        "yeah",
        "uh",
        "um",
        "like",
        "so",
        "alors",
        "donc",
    }
)
_HOOK_WORDS = frozenset(
    {
        "secret",
        "astuce",
        "important",
        "jamais",
        "toujours",
        "pourquoi",
        "comment",
        "attention",
        "erreur",
        "meilleur",
        "pire",
        "gratuit",
        "argent",
        "money",
        "hack",
        "tip",
        "why",
        "how",
        "never",
        "always",
        "stop",
        "must",
        "warning",
        "best",
        "worst",
        "free",
        "pro",
    }
)

# Titles that look like upload defaults / filenames — safe to overwrite
_FILENAMEISH = re.compile(
    r"^("
    r"untitled(\s+video)?|"
    r"nouvelle\s+vid[eé]o|"
    r"new\s+video|"
    r"vid[eé]o|"
    r"[\w.\- ]+\.(mp4|mov|webm|mkv|m4v|avi)|"
    r"[a-z0-9_\-]{2,80}"
    r")$",
    re.IGNORECASE,
)


def looks_like_default_title(name: str | None) -> bool:
    raw = (name or "").strip()
    if not raw:
        return True
    if len(raw) > 80:
        return False
    # Human titles usually have spaces + mixed case words, not pure file stems
    if _FILENAMEISH.match(raw):
        return True
    # "IMG_1234", "VID-2024", "Screen Recording 2024-01-01"
    if re.search(r"(img_|vid[_-]|screen.?recording|whatsapp|recording)", raw, re.I):
        return True
    if " " not in raw and re.fullmatch(r"[\w.\-]+", raw):
        return True
    return False


def _clean_sentence(text: str) -> str:
    s = re.sub(r"\s+", " ", text).strip(" \t\"'«»“”")
    s = re.sub(r"^[\-–—•]+\s*", "", s)
    return s.strip()


def _score_sentence(sentence: str) -> float:
    words = _WORD_RE.findall(sentence.lower())
    if not words:
        return -1.0
    if all(w in _FILLER_ONLY for w in words):
        return -1.0
    n = len(words)
    # Prefer ~4–14 words
    if n < 3:
        length_score = 0.15
    elif n <= 14:
        length_score = 1.0
    elif n <= 22:
        length_score = 0.55
    else:
        length_score = 0.2

    score = length_score
    if any(ch.isdigit() for ch in sentence):
        score += 0.35
    if any(w in _HOOK_WORDS for w in words):
        score += 0.45
    if sentence.strip().endswith("?"):
        score += 0.25
    if re.search(r"\b(je|tu|vous|on|i|you|we)\b", sentence, re.I):
        score += 0.1
    # Penalize very long walls of text
    if len(sentence) > 120:
        score -= 0.4
    return score


def _truncate_title(text: str, *, max_len: int = 72) -> str:
    text = _clean_sentence(text)
    if len(text) <= max_len:
        return text.rstrip(" .,:;")
    cut = text[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" .,:;") + "…"


def title_from_transcript_segments(
    segments: list[dict[str, Any]] | None,
    *,
    max_len: int = 72,
) -> str | None:
    """Pick first strong sentence, or the highest-scoring phrase in the transcript."""
    parts: list[str] = []
    for seg in segments or []:
        if isinstance(seg, dict) and seg.get("text"):
            parts.append(str(seg["text"]))
    blob = _clean_sentence(" ".join(parts))
    if not blob:
        return None

    sentences = [_clean_sentence(s) for s in _SENTENCE_SPLIT.split(blob) if _clean_sentence(s)]
    if not sentences:
        return _truncate_title(blob, max_len=max_len)

    scored = [(s, _score_sentence(s)) for s in sentences]
    scored = [(s, sc) for s, sc in scored if sc >= 0]
    if not scored:
        return _truncate_title(sentences[0], max_len=max_len)

    # Prefer first sentence if it's already decent
    first = scored[0]
    best = max(scored, key=lambda x: x[1])
    if first[1] >= 0.85 or (first[1] >= best[1] - 0.15 and first[1] >= 0.5):
        chosen = first[0]
    else:
        chosen = best[0]

    return _truncate_title(chosen, max_len=max_len)
