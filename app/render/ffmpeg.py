"""Deterministic FFmpeg command builder — never shell=True, never AI strings."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.constants import ErrorCode
from app.core.exceptions import AppException
from app.pipeline.sound_design.mixer import append_sfx_audio_filters, sfx_inputs_for_ffmpeg
from app.pipeline.timeline.event_schema import SfxEvent
from app.schemas.editplan import EditPlanDocument, ZoomOperation
from app.services.creative.cuts import edited_duration, keep_tuples, remap_interval

RESOLUTION_MAP: dict[tuple[str, str], tuple[int, int]] = {
    ("720p", "16:9"): (1280, 720),
    ("720p", "9:16"): (720, 1280),
    ("720p", "1:1"): (720, 720),
    ("720p", "4:5"): (720, 900),
    ("1080p", "16:9"): (1920, 1080),
    ("1080p", "9:16"): (1080, 1920),
    ("1080p", "1:1"): (1080, 1080),
    ("1080p", "4:5"): (1080, 1350),
}

# overlay_inputs: (path, start, end, layout) — times in OUTPUT (edited) clock
OverlayInput = tuple[Path, float, float, str]

FADE_IN = 0.35
FADE_OUT = 0.25


@dataclass(slots=True)
class RenderResult:
    output_path: Path
    stub: bool
    width: int
    height: int
    command: list[str]


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def output_size(plan: EditPlanDocument) -> tuple[int, int]:
    key = (plan.output.resolution, plan.output.aspect_ratio)
    return RESOLUTION_MAP.get(key, (720, 1280))


def _resolve_layout(layout: str) -> str:
    if layout in {"plate", "cover", "accent", "sticker", "background"}:
        if layout == "background":
            return "cover"
        if layout == "sticker":
            return "plate"
        return layout
    return "plate"


def _scale_fill(width: int, height: int) -> str:
    """Fill the export canvas (center crop) — CapCut-style, no letterbox."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


def _zoom_ops_output_clock(
    plan: EditPlanDocument,
    keeps: list[tuple[float, float]],
) -> list[tuple[float, float, float]]:
    """Remap zoom operations to output clock → (start, end, scale)."""
    out: list[tuple[float, float, float]] = []
    for op in plan.operations:
        if getattr(op, "type", None) != "zoom" and not isinstance(op, ZoomOperation):
            continue
        mapped = remap_interval(float(op.start), float(op.end), keeps)
        if mapped is None:
            continue
        out.append((mapped[0], mapped[1], float(op.scale)))
    return out


def _apply_zoom_chain(
    *,
    base_label: str,
    zooms: list[tuple[float, float, float]],
    width: int,
    height: int,
) -> tuple[list[str], str]:
    """Center-crop zoom for each window (output clock). Face focus later via focus_x/y."""
    if not zooms:
        return [], base_label
    parts: list[str] = []
    current = base_label
    for i, (start, end, scale) in enumerate(zooms):
        scaled = f"zs{i}"
        lab = f"z{i}"
        sw = max(width + 2, int(width * scale))
        sh = max(height + 2, int(height * scale))
        parts.append(
            f"[{current}]scale={sw}:{sh},crop={width}:{height}:(iw-ow)/2:(ih-oh)/2[{scaled}]"
        )
        parts.append(
            f"[{current}][{scaled}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[{lab}]"
        )
        current = lab
    return parts, current


def _build_overlay_chain(
    *,
    overlays: list[OverlayInput],
    width: int,
    height: int,
    first_overlay_input: int,
    base_label: str,
) -> tuple[list[str], str]:
    """Append overlay vf parts; return (parts, final_label)."""
    vf_parts: list[str] = []
    current = base_label
    for idx, (_path, start, end, layout_raw) in enumerate(overlays):
        layout = _resolve_layout(layout_raw)
        inp = first_overlay_input + idx
        fade_out_st = max(0.0, end - FADE_OUT)
        fade_chain = (
            f"format=rgba,"
            f"fade=t=in:st={start}:d={FADE_IN}:alpha=1,"
            f"fade=t=out:st={fade_out_st}:d={FADE_OUT}:alpha=1"
        )
        scaled = f"ov{idx}"
        out = f"v{idx}"

        if layout == "cover":
            dimmed = f"dim{idx}"
            vf_parts.append(
                f"[{current}]eq=brightness=-0.25:enable='between(t,{start},{end})'[{dimmed}]"
            )
            vf_parts.append(
                f"[{inp}:v]scale={int(width * 1.06)}:{int(height * 1.06)}"
                f":force_original_aspect_ratio=increase,"
                f"crop={width}:{height},{fade_chain}[{scaled}]"
            )
            vf_parts.append(
                f"[{dimmed}][{scaled}]overlay=0:0:enable='between(t,{start},{end})'[{out}]"
            )
        elif layout == "accent":
            ow = max(80, width // 4)
            vf_parts.append(f"[{inp}:v]scale={ow}:-1,{fade_chain}[{scaled}]")
            x = width - ow - 40
            y = height - ow - 160
            vf_parts.append(
                f"[{current}][{scaled}]overlay={x}:{y}:enable='between(t,{start},{end})'[{out}]"
            )
        else:
            ow = max(120, int(width * 0.6))
            vf_parts.append(f"[{inp}:v]scale={ow}:-1,{fade_chain}[{scaled}]")
            vf_parts.append(
                f"[{current}][{scaled}]overlay=(W-w)/2:(H-h)*0.55:"
                f"enable='between(t,{start},{end})'[{out}]"
            )
        current = out
    return vf_parts, current


def _sfx_events_from_plan(plan: EditPlanDocument) -> list[SfxEvent]:
    raw_events = (plan.events or {}).get("events") or []
    out: list[SfxEvent] = []
    for raw in raw_events:
        if not isinstance(raw, dict) or raw.get("type") != "sfx":
            continue
        try:
            out.append(SfxEvent.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


def build_ffmpeg_command(
    *,
    input_path: Path,
    output_path: Path,
    plan: EditPlanDocument,
    ass_path: Path | None = None,
    overlay_inputs: list[OverlayInput] | None = None,
) -> list[str]:
    """Build argv list for ffmpeg from EditPlan (+ ASS / overlays / zoom / SFX)."""
    width, height = output_size(plan)
    keeps = keep_tuples(plan.timeline.segments)
    if not keeps:
        raise AppException(
            "EditPlan has no timeline segments",
            code=ErrorCode.EDIT_PLAN_INVALID,
            status_code=422,
        )

    overlays = overlay_inputs or []
    out_dur = max(0.1, edited_duration(keeps))
    scale = _scale_fill(width, height)

    sfx_list: list[tuple[Path, float, float]] = []
    if getattr(plan.audio, "sfx_enabled", True):
        sfx_list = sfx_inputs_for_ffmpeg(_sfx_events_from_plan(plan), keeps=keeps)

    cmd: list[str] = ["ffmpeg", "-y", "-i", str(input_path)]
    for path, _s, _e, _layout in overlays:
        cmd.extend(["-loop", "1", "-t", str(out_dur), "-i", str(path)])
    for path, _start, _gain in sfx_list:
        cmd.extend(["-i", str(path)])

    vf_parts: list[str] = []
    af_parts: list[str] = []

    if len(keeps) == 1:
        a, b = keeps[0]
        vf_parts.append(
            f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,{scale}[base]"
        )
        af_parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[aok]")
        base = "base"
        first_ov = 1
    else:
        v_labels: list[str] = []
        a_labels: list[str] = []
        for i, (a, b) in enumerate(keeps):
            vl = f"vk{i}"
            al = f"ak{i}"
            vf_parts.append(
                f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,{scale}[{vl}]"
            )
            af_parts.append(
                f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[{al}]"
            )
            v_labels.append(f"[{vl}]")
            a_labels.append(f"[{al}]")
        n = len(keeps)
        vf_parts.append(f"{''.join(v_labels)}concat=n={n}:v=1:a=0[base]")
        af_parts.append(f"{''.join(a_labels)}concat=n={n}:v=0:a=1[aok]")
        base = "base"
        first_ov = 1

    zooms = _zoom_ops_output_clock(plan, keeps)
    zoom_parts, after_zoom = _apply_zoom_chain(
        base_label=base, zooms=zooms, width=width, height=height
    )
    vf_parts.extend(zoom_parts)

    ov_parts, current = _build_overlay_chain(
        overlays=overlays,
        width=width,
        height=height,
        first_overlay_input=first_ov,
        base_label=after_zoom,
    )
    vf_parts.extend(ov_parts)

    if ass_path and ass_path.exists():
        ass_esc = str(ass_path).replace("\\", "/").replace(":", "\\:")
        labeled = f"{current}_sub"
        vf_parts.append(f"[{current}]ass={ass_esc}[{labeled}]")
        current = labeled

    audio_filters: list[str] = []
    if plan.audio.denoise:
        audio_filters.append("highpass=f=80")
        audio_filters.append("afftdn=nf=-25")
    if plan.audio.normalize:
        audio_filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")

    voice_label = "aok"
    if audio_filters:
        af_parts.append(f"[aok]{','.join(audio_filters)}[avoice]")
        voice_label = "avoice"

    first_sfx = 1 + len(overlays)
    sfx_parts, audio_final = append_sfx_audio_filters(
        voice_label=voice_label,
        sfx_inputs=sfx_list,
        first_sfx_input_index=first_sfx,
    )
    af_parts.extend(sfx_parts)
    audio_map = f"[{audio_final}]"

    filter_complex = ";".join([*vf_parts, *af_parts])
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{current}]",
            "-map",
            audio_map,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
    )
    return cmd


def remap_overlays_to_output(
    overlays: list[OverlayInput],
    keeps: list[tuple[float, float]],
) -> list[OverlayInput]:
    """Remap overlay (path, start, end, layout) from source → output clock."""
    remapped: list[OverlayInput] = []
    for path, start, end, layout in overlays:
        mapped = remap_interval(start, end, keeps)
        if mapped is None:
            continue
        remapped.append((path, mapped[0], mapped[1], layout))
    return remapped


def remap_cues_to_output(
    cues: list[dict],
    keeps: list[tuple[float, float]],
) -> list[dict]:
    """Remap caption cue dicts from source → output clock."""
    out: list[dict] = []
    for cue in cues:
        start = float(cue.get("start", 0))
        end = float(cue.get("end", start + 1))
        mapped = remap_interval(start, end, keeps)
        if mapped is None:
            continue
        words_out = []
        for w in cue.get("words") or []:
            if not isinstance(w, dict):
                continue
            try:
                ws, we = float(w.get("start", 0)), float(w.get("end", 0))
            except (TypeError, ValueError):
                continue
            wm = remap_interval(ws, we, keeps)
            if wm is None:
                continue
            words_out.append({**w, "start": wm[0], "end": wm[1]})
        out.append({**cue, "start": mapped[0], "end": mapped[1], "words": words_out})
    return out


def run_ffmpeg_or_stub(
    *,
    input_path: Path | None,
    output_path: Path,
    plan: EditPlanDocument,
    force_stub: bool = False,
    source_bytes: bytes | None = None,
    ass_path: Path | None = None,
    overlay_inputs: list[OverlayInput] | None = None,
) -> RenderResult:
    """Execute ffmpeg when available; otherwise write a stub output file."""
    width, height = output_size(plan)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    use_stub = force_stub or not ffmpeg_available() or input_path is None or not input_path.exists()
    if use_stub:
        payload = source_bytes or (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256)
        output_path.write_bytes(payload)
        return RenderResult(
            output_path=output_path,
            stub=True,
            width=width,
            height=height,
            command=["stub"],
        )

    assert input_path is not None
    cmd = build_ffmpeg_command(
        input_path=input_path,
        output_path=output_path,
        plan=plan,
        ass_path=ass_path,
        overlay_inputs=overlay_inputs,
    )
    try:
        completed = subprocess.run(  # noqa: S603 — argv list, no shell
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:  # noqa: BLE001
        raise AppException(
            "FFmpeg execution failed",
            code=ErrorCode.RENDER_FAILED,
            status_code=502,
        ) from exc

    if completed.returncode != 0 or not output_path.exists():
        raise AppException(
            completed.stderr[:500] if completed.stderr else "FFmpeg failed",
            code=ErrorCode.RENDER_FAILED,
            status_code=502,
        )

    return RenderResult(
        output_path=output_path,
        stub=False,
        width=width,
        height=height,
        command=cmd,
    )
