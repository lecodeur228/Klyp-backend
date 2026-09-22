#!/usr/bin/env python3
"""Upload bundled SFX WAV files to Cloudinary and update the library manifest.

Usage (from Klyp-backend, with CLOUDINARY_* in .env):

  uv run python scripts/import_sfx_cloudinary.py
  uv run python scripts/import_sfx_cloudinary.py --force
  uv run python scripts/import_sfx_cloudinary.py --dry-run

Uploads to folder: klyp/sfx/{category}/{asset_id}
Writes public_id + secure_url (+ duration_ms when available) into
app/pipeline/sound_design/sfx_library/manifest.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cloudinary.uploader  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.pipeline.sound_design.placement import (  # noqa: E402
    LIBRARY_DIR,
    clear_manifest_cache,
    load_manifest,
    save_manifest,
)
from app.storage.cloudinary_storage import CloudinaryStorage, configure_cloudinary  # noqa: E402


async def _upload_one(
    *,
    asset: dict[str, Any],
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    asset_id = str(asset.get("id") or "")
    category = str(asset.get("category") or "misc")
    rel = asset.get("file")
    if not asset_id or not isinstance(rel, str) or not rel:
        print(f"  skip (missing id/file): {asset}")
        return asset

    path = LIBRARY_DIR / rel
    if not path.exists():
        print(f"  skip (file missing): {path}")
        return asset

    existing_url = asset.get("secure_url")
    if (
        not force
        and isinstance(existing_url, str)
        and existing_url.startswith("http")
        and asset.get("public_id")
    ):
        print(f"  keep {asset_id} (already on Cloudinary)")
        return asset

    folder = f"klyp/sfx/{category}"
    public_id = f"{folder}/{asset_id}"
    print(f"  upload {asset_id} → {public_id} …")
    if dry_run:
        return {
            **asset,
            "public_id": public_id,
            "secure_url": f"https://res.cloudinary.com/example/video/upload/{public_id}",
        }

    content = path.read_bytes()

    def _upload() -> dict:
        return cloudinary.uploader.upload(
            content,
            public_id=public_id,
            resource_type="video",  # Cloudinary stores audio under video
            overwrite=True,
            invalidate=True,
        )

    raw = await asyncio.to_thread(_upload)
    duration = raw.get("duration")
    duration_ms = (
        int(round(float(duration) * 1000))
        if isinstance(duration, (int, float))
        else asset.get("duration_ms")
    )
    return {
        **asset,
        "public_id": str(raw.get("public_id") or public_id),
        "secure_url": str(raw.get("secure_url") or raw.get("url") or ""),
        "duration_ms": duration_ms,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import SFX library to Cloudinary")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload even if secure_url is already set",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without uploading or writing manifest",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not args.dry_run and not settings.cloudinary_configured:
        print("Cloudinary is not configured (CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET).")
        print("Add credentials to .env, or pass --dry-run to preview.")
        return 1

    if not args.dry_run:
        # Ensure SDK config + credentials are valid
        _ = CloudinaryStorage(settings)
        configure_cloudinary(settings)

    clear_manifest_cache()
    manifest = dict(load_manifest())
    assets = list(manifest.get("assets") or [])
    if not assets:
        print("No assets in manifest.")
        return 1

    updated: list[dict[str, Any]] = []
    print(f"Importing {len(assets)} SFX asset(s)…")
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        next_asset = await _upload_one(
            asset=raw, force=args.force, dry_run=args.dry_run
        )
        updated.append(next_asset)

    on_cdn = sum(
        1
        for a in updated
        if isinstance(a.get("secure_url"), str)
        and str(a["secure_url"]).startswith("http")
    )
    manifest["assets"] = updated
    manifest["storage"] = "cloudinary" if on_cdn == len(updated) else "hybrid"
    manifest["folder"] = "klyp/sfx"

    if args.dry_run:
        print(
            f"Dry-run OK — would mark storage={manifest['storage']} "
            f"({on_cdn}/{len(updated)} on CDN)"
        )
        return 0

    save_manifest(manifest)
    print(
        f"Wrote {LIBRARY_DIR / 'manifest.json'} "
        f"(storage={manifest['storage']}, {on_cdn}/{len(updated)} on CDN)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
