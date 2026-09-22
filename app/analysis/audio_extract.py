"""Extract clean 16 kHz mono WAV for ASR (never transcribe compressed video mux)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def download_media(url: str, *, timeout: float = 180.0) -> Path:
    """Download remote media to a temp file; return path (caller must delete parent)."""
    suffix = ".mp4"
    lower = url.lower().split("?", 1)[0]
    for ext in (".mp3", ".wav", ".m4a", ".mov", ".webm", ".mp4"):
        if lower.endswith(ext):
            suffix = ext
            break
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    tmp.close()
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        tmp_path.write_bytes(resp.content)
    return tmp_path


def extract_wav_16k(
    source: Path | str,
    *,
    output: Path | None = None,
) -> Path:
    """Re-sample to mono 16 kHz PCM WAV via FFmpeg."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found — required for clean ASR audio extract")
    src = Path(source)
    out = output or Path(tempfile.mkstemp(suffix=".wav")[1])
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    completed = subprocess.run(  # noqa: S603
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0 or not out.exists() or out.stat().st_size < 44:
        raise RuntimeError(
            completed.stderr[:400] if completed.stderr else "ffmpeg wav extract failed"
        )
    return out
