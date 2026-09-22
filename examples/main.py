#!/usr/bin/env python3
"""Higgsfield Seedance 2.5 text-to-video example (server-side only).

Requires HF_KEY in .env.local (key-id:key-secret). Never commit credentials.

  uv run python examples/main.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env_local() -> None:
    """Load .env.local then .env without printing values."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[assignment]

    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.is_file():
            continue
        if load_dotenv is not None:
            load_dotenv(path, override=False)
            continue
        # Minimal fallback if python-dotenv is unavailable
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, _, value = raw.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def _video_url(result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    video = result.get("video")
    if isinstance(video, dict):
        url = video.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    if isinstance(video, str) and video.startswith("http"):
        return video
    # Some payloads nest under data
    data = result.get("data")
    if isinstance(data, dict):
        return _video_url(data)
    return None


def main() -> int:
    _load_env_local()
    key = os.environ.get("HF_KEY", "").strip()
    if not key or ":" not in key:
        print(
            "HF_KEY missing or invalid. Add key-id:key-secret to .env.local "
            "(gitignored). Do not put credentials in chat.",
            file=sys.stderr,
        )
        return 1

    # Ensure the SDK sees HF_KEY from the environment
    os.environ["HF_KEY"] = key

    import higgsfield_client

    print("Submitting bytedance/seedance-2.5/text-to-video …")

    def _on_update(status: object) -> None:
        name = type(status).__name__
        print(f"  status: {name}")

    try:
        result = higgsfield_client.subscribe(
            "bytedance/seedance-2.5/text-to-video",
            arguments={
                "prompt": "A cinematic scene at sunset",
                "duration": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
            },
            on_queue_update=_on_update,
        )
    except higgsfield_client.CredentialsMissedError:
        print("HF_KEY not picked up by the SDK.", file=sys.stderr)
        return 1
    except higgsfield_client.InsufficientCreditsError as exc:
        print(f"Insufficient credits: {exc}", file=sys.stderr)
        return 2
    except higgsfield_client.HiggsfieldClientError as exc:
        msg = str(exc).lower()
        if "not_enough_credits" in msg or "insufficient" in msg:
            print(f"Insufficient credits: {exc}", file=sys.stderr)
            return 2
        print(f"Higgsfield error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — surface SDK/network failures
        print(f"Request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    status = None
    if isinstance(result, dict):
        status = result.get("status")
    status_norm = str(status or "").lower()

    if status_norm in {"failed", "canceled", "cancelled", "nsfw", "moderated"}:
        err = None
        if isinstance(result, dict):
            err = result.get("error") or result.get("message")
        print(
            f"Generation did not succeed (status={status_norm})"
            + (f": {err}" if err else ""),
            file=sys.stderr,
        )
        return 2

    url = _video_url(result)
    if not url:
        # subscribe may return the completed payload without an explicit status
        if status_norm and status_norm not in {"completed", "success", ""}:
            print(
                f"Unexpected status={status_norm}; no video URL in response.",
                file=sys.stderr,
            )
            return 2
        print(
            "Completed response had no video URL; refusing to claim success.",
            file=sys.stderr,
        )
        if isinstance(result, dict):
            # Safe keys only — never dump credentials
            print(f"Response keys: {sorted(result.keys())}", file=sys.stderr)
        return 2

    if status_norm and status_norm not in {"completed", "success", ""}:
        print(
            f"Refusing success: status={status_norm} but URL present.",
            file=sys.stderr,
        )
        return 2

    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
