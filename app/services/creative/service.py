"""Creative plan service — AI style + illustrative overlays after ASR."""

from __future__ import annotations

import copy
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.registry import render_prompt
from app.ai.providers import build_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundException, ValidationException
from app.models.analysis import VideoAnalysis
from app.models.asset import Asset
from app.models.edit_plan import EditPlan
from app.models.video import Video
from app.schemas.editplan import (
    AudioConfig,
    CaptionPosition,
    CaptionScale,
    CaptionsConfig,
    CreativePlanPublic,
    CreativePlanValidateRequest,
    CreativePlanZoom,
    EditPlanDocument,
    OutputConfig,
    Timeline,
    TimelineSegment,
    VisualOverlay,
    VisualStyle,
)
from app.services.creative.cuts import (
    build_keep_segments,
    keep_tuples,
    source_to_output,
)
from app.pipeline.enrich import enrich_edit_plan
from app.pipeline.transcription.qa_check import evaluate_sync_qa
from app.services.videos import service as videos_service
from app.storage import get_storage

logger = logging.getLogger(__name__)

VISUAL_STYLES = frozenset({"prism", "paper", "prime", "elevate", "pulse"})

_PACE_KEYS = (
    "coupe",
    "silence",
    "rythme",
    "pace",
    "rapide",
    "cut",
    "tight",
    "dynamique",
    "tiktok",
    "punchy",
    "énergie",
    "energie",
    "energy",
)
_ZOOM_KEYS = ("zoom", "punch", "dynamique", "énergie", "energie", "energy", "proche")


def _brief_aggressiveness(brief: str) -> float:
    b = brief.lower()
    if any(k in b for k in _PACE_KEYS):
        return 1.85
    return 1.0


def _brief_zoom_budget(brief: str) -> float:
    b = brief.lower()
    if any(k in b for k in _ZOOM_KEYS) or any(k in b for k in _PACE_KEYS):
        return 7.0
    return 4.0


def _coerce_visual_style(raw: str | None) -> VisualStyle:
    """Accept featured aliases or any catalog preset id."""
    from app.pipeline.subtitles.presets_loader import list_preset_ids

    value = (raw or "prism").strip()
    if value in VISUAL_STYLES:
        return value  # type: ignore[return-value]
    if value in list_preset_ids():
        return value  # type: ignore[return-value]
    return "prism"  # type: ignore[return-value]
CAPTION_POSITIONS = frozenset({"bottom", "lower", "top"})
CAPTION_SCALES = frozenset({"sm", "md", "lg"})
CREATIVE_SCHEMA: dict[str, Any] = {
    "title": "CreativePlan",
    "type": "object",
    "properties": {
        "visual_style": {"type": "string"},
        "captions_mode": {"type": "string"},
        "overlays": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "kind": {"type": "string"},
                    "layout": {"type": "string"},
                    "prompt": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}
PLACEMENT_SCHEMA: dict[str, Any] = {
    "title": "CaptionPlacement",
    "type": "object",
    "properties": {
        "position": {"type": "string"},
        "scale": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["position", "scale"],
}


def _aspect_from_asset(asset: Asset) -> str:
    w = asset.width or 0
    h = asset.height or 0
    if w and h and h > w:
        return "9:16"
    if w and h and w == h:
        return "1:1"
    return "16:9"


def _transcript_text(analysis: VideoAnalysis) -> str:
    parts: list[str] = []
    for seg in analysis.segments or []:
        if isinstance(seg, dict) and seg.get("text"):
            parts.append(str(seg["text"]))
    return "\n".join(parts)[:6000] or "(empty)"


def _timed_transcript(analysis: VideoAnalysis) -> str:
    lines: list[str] = []
    for seg in analysis.segments or []:
        if not isinstance(seg, dict) or not seg.get("text"):
            continue
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue
        lines.append(f"[{start:.2f}-{end:.2f}] {str(seg['text']).strip()}")
    return "\n".join(lines)[:8000] or "(empty)"


def _format_keeps(keeps: list[TimelineSegment]) -> str:
    if not keeps:
        return "(full timeline)"
    return ", ".join(f"[{s.start:.2f}-{s.end:.2f}]" for s in keeps)


def cloudinary_frame_urls(secure_url: str, *, duration: float) -> list[str]:
    """Build 2–3 JPEG frame URLs via Cloudinary video transforms."""
    marker = "/upload/"
    if "res.cloudinary.com" not in secure_url or marker not in secure_url:
        return []
    head, tail = secure_url.split(marker, 1)
    # Drop existing transforms if any (f_mp3 etc.)
    if "/" in tail and not tail.startswith("v"):
        # e.g. f_mp3/v123/... → keep from version folder
        parts = tail.split("/")
        for i, p in enumerate(parts):
            if p.startswith("v") and p[1:].isdigit():
                tail = "/".join(parts[i:])
                break
    total = duration if duration and duration > 0 else 10.0
    stamps = sorted({max(0.1, total * 0.2), max(0.1, total * 0.5), max(0.1, total * 0.7)})
    urls: list[str] = []
    for t in stamps[:3]:
        urls.append(
            f"{head}{marker}so_{t:.2f},w_512,h_512,c_fill,f_jpg/{tail}"
        )
    return urls


async def _suggest_caption_layout(
    *,
    provider: Any,
    media_url: str | None,
    duration: float,
    settings: Settings,
) -> tuple[CaptionPosition, CaptionScale]:
    """Vision pass on sample frames → safe caption band + scale."""
    defaults: tuple[CaptionPosition, CaptionScale] = ("lower", "md")
    if settings.ai_provider == "fake" or not media_url:
        return defaults
    frames = cloudinary_frame_urls(media_url, duration=duration)
    if not frames:
        return defaults
    try:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "You place burned-in captions on a short talking-head video. "
                    "Look at these frames. Prefer position that does NOT cover the face "
                    "or upper torso. Prefer 'lower' or 'bottom' for centered faces; "
                    "use 'top' only if the face/subject is clearly in the lower half. "
                    "Scale: sm for busy frames, md default, lg only if lots of empty space. "
                    "This is a caption placement decision."
                ),
            }
        ]
        for url in frames:
            content.append(
                {"type": "image_url", "image_url": {"url": url}}
            )
        result = await provider.generate_structured(
            messages=[{"role": "user", "content": content}],
            schema=PLACEMENT_SCHEMA,
        )
        pos = str(result.data.get("position") or "lower")
        scale = str(result.data.get("scale") or "md")
        if pos not in CAPTION_POSITIONS:
            pos = "lower"
        if scale not in CAPTION_SCALES:
            scale = "md"
        return pos, scale  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        logger.exception("caption placement vision failed — using defaults")
        return defaults


def _fake_creative(
    *,
    duration: float,
    transcript: str,
) -> dict[str, Any]:
    total = duration if duration > 0 else 30.0
    style: VisualStyle = "prime"
    lower = transcript.lower()
    if "immobilier" in lower or "estate" in lower or "prix" in lower:
        style = "prism"
    elif "leçon" in lower or "lesson" in lower or "appr" in lower:
        style = "elevate"
    elif "papier" in lower or "idée" in lower:
        style = "paper"

    overlays: list[dict[str, Any]] = []
    if total >= 8:
        mid = round(total * 0.35, 2)
        overlays.append(
            {
                "start": mid,
                "end": round(min(total, mid + 3.0), 2),
                "layout": "plate",
                "kind": "sticker",
                "prompt": (
                    "Clean illustration of the spoken concept, centered subject, "
                    "soft gradient background, no text, high clarity"
                ),
            }
        )
    if total >= 20:
        t2 = round(total * 0.7, 2)
        overlays.append(
            {
                "start": t2,
                "end": round(min(total, t2 + 2.5), 2),
                "layout": "cover",
                "kind": "background",
                "prompt": (
                    "Cinematic full-frame scene matching the spoken mood, "
                    "no text, suitable as a short B-roll cutaway"
                ),
            }
        )
    return {
        "visual_style": style,
        "captions_mode": "dynamic",
        "overlays": overlays,
    }


def _resolve_layout(item: dict[str, Any]) -> str:
    layout = item.get("layout")
    if layout in {"plate", "cover", "accent"}:
        return str(layout)
    kind = item.get("kind")
    if kind == "background":
        return "cover"
    # Default monteur insert — accent only when explicitly set
    return "plate"


def _kind_for_layout(layout: str) -> str:
    return "background" if layout == "cover" else "sticker"


def _enrich_image_prompt(prompt: str, *, layout: str) -> str:
    base = prompt.strip()
    if layout == "cover":
        suffix = (
            " Full-bleed cinematic frame, edge-to-edge composition, no text, no watermark."
        )
    elif layout == "accent":
        suffix = (
            " Simple flat icon, single subject, transparent or plain background, no text."
        )
    else:
        suffix = (
            " Large clear subject for a centered video insert, soft background, no text."
        )
    return (base + suffix)[:500]


def _normalize_overlays(
    raw: list[dict[str, Any]] | None,
    *,
    duration: float,
    keep_segments: list[TimelineSegment] | None = None,
) -> list[VisualOverlay]:
    keeps = keep_tuples(keep_segments or [])
    out: list[VisualOverlay] = []
    for i, item in enumerate((raw or [])[:5]):
        try:
            start = float(item.get("start", 0))
            end = float(item.get("end", start + 2))
        except (TypeError, ValueError):
            continue
        # Professional duration bounds
        if end <= start:
            end = start + 2.0
        span = end - start
        if span < 1.2:
            end = start + 1.5
        elif span > 4.0:
            end = start + 3.5
        if duration > 0:
            start = max(0.0, min(start, duration))
            end = max(start + 0.2, min(end, duration))
        # Snap into a keep range if possible
        if keeps and source_to_output(start, keeps) is None:
            snapped = False
            for a, b in keeps:
                if b - a < 1.0:
                    continue
                mid = (a + b) / 2
                if abs(mid - start) < 8.0 or (start < a < end) or (a <= start <= b):
                    start = a + min(0.3, (b - a) * 0.1)
                    end = min(b, start + max(1.5, min(3.5, span)))
                    snapped = True
                    break
            if not snapped:
                continue
        elif keeps and source_to_output(end, keeps) is None:
            for a, b in keeps:
                if a <= start <= b:
                    end = min(b, max(start + 1.2, end))
                    break
        layout = _resolve_layout(item)
        kind = item.get("kind") if item.get("kind") in {"sticker", "background"} else None
        if kind is None:
            kind = _kind_for_layout(layout)
        prompt = str(item.get("prompt") or "").strip()
        if len(prompt) < 3:
            continue
        out.append(
            VisualOverlay(
                id=f"ov-{i + 1}-{uuid4().hex[:6]}",
                start=round(start, 3),
                end=round(end, 3),
                kind=kind,  # type: ignore[arg-type]
                layout=layout,  # type: ignore[arg-type]
                prompt=prompt[:500],
                status="proposed",
            )
        )
    return out


def _document_from_creative(
    *,
    video_id: str,
    duration: float,
    aspect: str,
    visual_style: VisualStyle,
    captions_mode: str,
    overlays: list[VisualOverlay],
    keep_segments: list[TimelineSegment] | None = None,
    captions_position: CaptionPosition = "lower",
    captions_scale: CaptionScale = "md",
) -> EditPlanDocument:
    mode = captions_mode if captions_mode in {"minimal", "dynamic"} else "dynamic"
    timeline_segs = keep_segments or [
        TimelineSegment(id="keep-1", start=0.0, end=max(duration, 0.1))
    ]
    return EditPlanDocument(
        schema_version="1.5.0",
        source_video_id=video_id,
        timeline=Timeline(segments=timeline_segs),
        operations=[],
        captions=CaptionsConfig(
            enabled=True,
            style=mode,  # type: ignore[arg-type]
            theme=visual_style,
            position=captions_position,
            scale=captions_scale,
        ),
        visual_style=visual_style,
        overlays=overlays,
        audio=AudioConfig(denoise=True, normalize=True, sfx_enabled=True),
        output=OutputConfig(
            resolution="720p",
            aspect_ratio=aspect if aspect in {"9:16", "16:9", "1:1", "4:5"} else "9:16",  # type: ignore[arg-type]
        ),
    )


async def _get_plan_for_video(
    session: AsyncSession, *, video_id: str
) -> EditPlan | None:
    result = await session.execute(
        select(EditPlan).where(EditPlan.source_video_id == video_id)
    )
    return result.scalar_one_or_none()


MONTEUR_LAYOUT_SCHEMA = "1.3.1"


def _schema_version_lt(version: str | None, target: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in value.split(".")[:3])
        except ValueError:
            return (0, 0, 0)

    return parts(version or "0") < parts(target)


def _migrate_monteur_layouts(plan: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """One-shot soft migrate: legacy sticker→accent defaults become plate."""
    if not _schema_version_lt(str(plan.get("schema_version") or "0"), MONTEUR_LAYOUT_SCHEMA):
        return plan, False

    migrated = copy.deepcopy(plan)
    overlays = migrated.get("overlays")
    if isinstance(overlays, list):
        for item in overlays:
            if not isinstance(item, dict):
                continue
            layout = item.get("layout")
            kind = item.get("kind")
            if layout == "cover" or kind == "background":
                if layout != "cover":
                    item["layout"] = "cover"
                continue
            # Missing layout or legacy accent (old sticker default) → plate
            if layout not in {"plate", "cover", "accent"} or layout == "accent":
                item["layout"] = "plate"
    migrated["schema_version"] = MONTEUR_LAYOUT_SCHEMA
    return migrated, True


def to_creative_public(row: EditPlan | None, *, video_id: str, project_id: str) -> CreativePlanPublic:
    if not row:
        return CreativePlanPublic(
            video_id=video_id,
            project_id=project_id,
            status="missing",
            validated=False,
        )
    plan = EditPlanDocument.model_validate(row.plan or {"source_video_id": video_id})
    zooms = [
        CreativePlanZoom(start=float(op.start), end=float(op.end), scale=float(op.scale))
        for op in plan.operations
        if getattr(op, "type", None) == "zoom"
    ]
    return CreativePlanPublic(
        video_id=video_id,
        project_id=project_id,
        edit_plan_id=row.id,
        status=row.status,
        visual_style=plan.visual_style,
        captions_mode=plan.captions.style,
        captions_position=plan.captions.position,
        captions_scale=plan.captions.scale,
        overlays=plan.overlays,
        timeline_segments=list(plan.timeline.segments),
        zooms=zooms,
        validated=row.status in {"ready", "validated"},
    )


async def run_creative_plan_for_video(
    session: AsyncSession,
    *,
    video_id: str,
    settings: Settings | None = None,
    user_prompt: str | None = None,
) -> EditPlan:
    """Generate AI creative proposals and upsert EditPlan (status=proposed)."""
    settings = settings or get_settings()
    brief = (user_prompt or "").strip()
    video = (
        await session.execute(select(Video).where(Video.id == video_id))
    ).scalar_one_or_none()
    if not video:
        raise NotFoundException("Video not found")

    asset = (
        await session.execute(select(Asset).where(Asset.id == video.original_asset_id))
    ).scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset not found")

    analysis = (
        await session.execute(
            select(VideoAnalysis).where(VideoAnalysis.video_id == video_id)
        )
    ).scalar_one_or_none()
    if not analysis or analysis.status not in {"ready", "completed"}:
        raise ValidationException("Analysis not ready")

    duration = float(asset.duration) if asset.duration else 30.0
    aspect = _aspect_from_asset(asset)
    aggressiveness = _brief_aggressiveness(brief)
    zoom_budget = _brief_zoom_budget(brief)
    keep_segments = build_keep_segments(
        duration=duration,
        segments=list(analysis.segments or []),
        vad_segments=list(analysis.vad_segments or []),
        fillers=list(analysis.fillers or []),
        aggressiveness=aggressiveness,
    )
    transcript = _timed_transcript(analysis)
    keeps_text = _format_keeps(keep_segments)

    data: dict[str, Any]
    provider = build_provider(settings)
    if settings.ai_provider == "fake":
        data = _fake_creative(duration=duration, transcript=transcript)
    else:
        try:
            system, user, _ = render_prompt(
                "creative_plan",
                user_brief=brief or "(none — use best judgment for short-form)",
                source_video_id=video_id,
                duration=str(round(duration, 2)),
                aspect=aspect,
                transcript=transcript,
                keep_ranges=keeps_text,
            )
            result = await provider.generate_structured(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                schema=CREATIVE_SCHEMA,
                model=settings.rodiumai_plan_model,
            )
            data = result.data
        except Exception:  # noqa: BLE001
            logger.exception("creative_plan AI failed — using heuristic fallback")
            data = _fake_creative(duration=duration, transcript=transcript)

    style_raw = str(data.get("visual_style") or "prism")
    visual_style: VisualStyle = _coerce_visual_style(style_raw)
    overlays = _normalize_overlays(
        data.get("overlays"),
        duration=duration,
        keep_segments=keep_segments,
    )

    cap_pos, cap_scale = await _suggest_caption_layout(
        provider=provider,
        media_url=asset.secure_url,
        duration=duration,
        settings=settings,
    )
    # Pace briefs: push visible caption energy so the preview actually changes.
    if aggressiveness > 1.0:
        data["captions_mode"] = "dynamic"
        cap_scale = "lg"

    document = _document_from_creative(
        video_id=video_id,
        duration=duration,
        aspect=aspect,
        visual_style=visual_style,
        captions_mode=str(data.get("captions_mode") or "dynamic"),
        overlays=overlays,
        keep_segments=keep_segments,
        captions_position=cap_pos,
        captions_scale=cap_scale,
    )
    qa = evaluate_sync_qa(
        vad_segments=list(analysis.vad_segments or []),
        segments=list(analysis.segments or []),
        aligned=bool(getattr(analysis, "aligned", False)),
        quality_warning=analysis.quality_warning,
    )
    document = enrich_edit_plan(
        plan=document,
        duration=duration,
        analysis_segments=list(analysis.segments or []),
        global_subject=_transcript_text(analysis)[:120],
        art_direction=f"{visual_style} consistent palette",
        needs_review=bool(qa.get("needs_review")),
        dry_run=False,
        zoom_budget_per_min=zoom_budget,
    )

    stored_prompt = brief if brief else "auto:creative_plan"
    row = await _get_plan_for_video(session, video_id=video_id)
    if row is None:
        row = EditPlan(
            project_id=video.project_id,
            source_video_id=video.id,
            analysis_id=analysis.id,
            version=1,
            prompt=stored_prompt,
            plan=document.model_dump(mode="json"),
            status="proposed",
        )
        session.add(row)
    else:
        row.analysis_id = analysis.id
        row.plan = document.model_dump(mode="json")
        row.status = "proposed"
        row.version = int(row.version or 1) + 1
        row.prompt = stored_prompt

    await session.flush()
    await session.refresh(row)
    return row


async def get_creative_plan(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
) -> CreativePlanPublic:
    video, _asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=video_id
    )
    row = await _get_plan_for_video(session, video_id=video_id)
    if row and isinstance(row.plan, dict):
        migrated, changed = _migrate_monteur_layouts(row.plan)
        if changed:
            row.plan = migrated
            await session.commit()
            await session.refresh(row)
    return to_creative_public(row, video_id=video.id, project_id=video.project_id)


async def validate_creative_plan(
    session: AsyncSession,
    *,
    user_id: str,
    video_id: str,
    body: CreativePlanValidateRequest,
    settings: Settings | None = None,
) -> CreativePlanPublic:
    settings = settings or get_settings()
    video, _asset = await videos_service.get_owned_video(
        session, user_id=user_id, video_id=video_id
    )
    row = await _get_plan_for_video(session, video_id=video_id)
    if not row:
        raise NotFoundException("Creative plan not found")

    plan = EditPlanDocument.model_validate(row.plan or {"source_video_id": video_id})
    if body.visual_style:
        plan.visual_style = body.visual_style
        plan.captions.theme = body.visual_style
    if body.captions_mode:
        plan.captions.style = body.captions_mode
    if body.captions_position:
        plan.captions.position = body.captions_position
    if body.captions_scale:
        plan.captions.scale = body.captions_scale

    if body.overlay_layouts:
        by_id = {p.id: p.layout for p in body.overlay_layouts}
        plan.overlays = [
            ov.model_copy(
                update={
                    "layout": by_id[ov.id],
                    "kind": _kind_for_layout(by_id[ov.id]),  # type: ignore[arg-type]
                }
            )
            if ov.id in by_id
            else ov
            for ov in plan.overlays
        ]

    mutating_overlays = bool(
        body.accept_all or body.accept_overlay_ids or body.reject_overlay_ids
    )
    if mutating_overlays:
        accept_ids = set(body.accept_overlay_ids)
        reject_ids = set(body.reject_overlay_ids)
        updated: list[VisualOverlay] = []
        for ov in plan.overlays:
            if body.accept_all or ov.id in accept_ids:
                ov = ov.model_copy(update={"status": "accepted"})
            elif ov.id in reject_ids:
                ov = ov.model_copy(update={"status": "rejected"})
            updated.append(ov)

        # Generate images for accepted overlays missing assets
        provider = build_provider(settings)
        storage = get_storage(settings)
        for i, ov in enumerate(updated):
            if ov.status != "accepted" or ov.asset_url:
                continue
            try:
                image = await provider.generate_image(
                    prompt=_enrich_image_prompt(ov.prompt, layout=ov.layout)
                )
                uploaded = await storage.save_media(
                    filename=f"{ov.id}.png",
                    content=image.content,
                    content_type=image.mime_type or "image/png",
                    folder=f"projects/{video.project_id}/overlays",
                )
                updated[i] = ov.model_copy(
                    update={"status": "ready", "asset_url": uploaded.secure_url}
                )
            except Exception:  # noqa: BLE001
                logger.exception("overlay image gen failed id=%s", ov.id)
                # Keep accepted without URL — preview can skip

        plan.overlays = updated
        row.status = "ready"

    row.plan = plan.model_dump(mode="json")
    await session.flush()
    await session.refresh(row)
    return to_creative_public(row, video_id=video.id, project_id=video.project_id)
