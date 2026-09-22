"""Module 4 — mix SFX into FFmpeg filter graph (adelay + amix)."""

from __future__ import annotations

from pathlib import Path

from app.pipeline.sound_design.placement import resolve_asset_path
from app.pipeline.timeline.event_schema import SfxEvent
from app.services.creative.cuts import remap_interval


def sfx_inputs_for_ffmpeg(
    events: list[SfxEvent],
    *,
    keeps: list[tuple[float, float]],
) -> list[tuple[Path, float, float]]:
    """Return (wav_path, output_start_s, volume_linear) for each remapped SFX."""
    out: list[tuple[Path, float, float]] = []
    for ev in events:
        if not ev.asset_id:
            continue
        path = resolve_asset_path(ev.asset_id)
        if path is None or not path.exists():
            continue
        mapped = remap_interval(ev.start, ev.end, keeps)
        if mapped is None:
            continue
        # volume_db → linear gain
        gain = 10 ** (ev.volume_db / 20.0)
        out.append((path, mapped[0], gain))
    return out


def append_sfx_audio_filters(
    *,
    voice_label: str,
    sfx_inputs: list[tuple[Path, float, float]],
    first_sfx_input_index: int,
) -> tuple[list[str], str]:
    """Build af parts that adelay+volume each SFX and amix with voice.

    Returns (af_parts, final_audio_label).
    """
    if not sfx_inputs:
        return [], voice_label

    parts: list[str] = []
    labels: list[str] = [f"[{voice_label}]"]
    for i, (_path, start_s, gain) in enumerate(sfx_inputs):
        inp = first_sfx_input_index + i
        delay_ms = max(0, int(round(start_s * 1000)))
        lab = f"sfx{i}"
        # adelay needs channel layout; use all=1 for mono/stereo
        parts.append(
            f"[{inp}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={gain:.4f},adelay={delay_ms}|{delay_ms}[{lab}]"
        )
        labels.append(f"[{lab}]")
    n = len(labels)
    parts.append(
        f"{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0:normalize=0[amixed]"
    )
    return parts, "amixed"
