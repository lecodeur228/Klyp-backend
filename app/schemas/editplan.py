"""EditPlan Pydantic schemas — central montage contract (ADR-0005)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

AspectRatio = Literal["9:16", "16:9", "1:1", "4:5"]
Resolution = Literal["720p", "1080p"]
CaptionStyle = Literal["minimal", "dynamic"]
CaptionPosition = Literal["bottom", "lower", "top"]
CaptionScale = Literal["sm", "md", "lg"]
# Preset id: featured aliases (prism…) or catalog ids (001-hype-drop…)
VisualStyle = str
OverlayKind = Literal["sticker", "background"]
OverlayLayout = Literal["plate", "cover", "accent"]
OverlayStatus = Literal["proposed", "accepted", "rejected", "ready"]
CropMode = Literal["smart", "center"]


FEATURED_VISUAL_STYLES = frozenset({"prism", "paper", "prime", "elevate", "pulse"})


def normalize_visual_style(value: str | None, *, default: str = "prism") -> str:
    raw = (value or default).strip()
    return raw or default


class TimelineSegment(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class Timeline(BaseModel):
    segments: list[TimelineSegment] = Field(default_factory=list)


class ZoomOperation(BaseModel):
    type: Literal["zoom"] = "zoom"
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    scale: float = Field(gt=1.0, le=5.0)


class CropOperation(BaseModel):
    type: Literal["crop"] = "crop"
    aspect_ratio: AspectRatio
    mode: CropMode = "smart"


EditOperation = Annotated[ZoomOperation | CropOperation, Field(discriminator="type")]


class CaptionsConfig(BaseModel):
    enabled: bool = True
    style: CaptionStyle = "dynamic"
    theme: VisualStyle = "prism"
    position: CaptionPosition = "lower"
    scale: CaptionScale = "md"


class VisualOverlay(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    kind: OverlayKind = "sticker"
    layout: OverlayLayout = "plate"
    prompt: str = Field(min_length=1, max_length=500)
    status: OverlayStatus = "proposed"
    asset_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_layout_from_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("layout") in {"plate", "cover", "accent"}:
            return data
        kind = data.get("kind")
        if kind == "background":
            data["layout"] = "cover"
        else:
            # sticker or unknown → large monteur insert (not corner accent)
            data["layout"] = "plate"
        return data


class AudioConfig(BaseModel):
    denoise: bool = True
    normalize: bool = True
    # SFX mix: duck under voice peak by this many dB (Module 4)
    sfx_relative_db: float = Field(default=-5.0, le=0.0, ge=-24.0)
    sfx_enabled: bool = True


class OutputConfig(BaseModel):
    resolution: Resolution = "720p"
    aspect_ratio: AspectRatio = "9:16"


class EditPlanDocument(BaseModel):
    """Validated EditPlan body stored in DB JSON."""

    schema_version: str = "1.5.0"
    source_video_id: str
    timeline: Timeline = Field(default_factory=Timeline)
    operations: list[ZoomOperation | CropOperation] = Field(default_factory=list)
    captions: CaptionsConfig = Field(default_factory=CaptionsConfig)
    visual_style: VisualStyle = "prism"
    overlays: list[VisualOverlay] = Field(default_factory=list)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    # Shared event timeline (Module pipeline) — optional for back-compat with 1.4 plans
    events: dict[str, Any] | None = None


class AiEditRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class AiEditStarted(BaseModel):
    job_id: str
    edit_plan_id: str
    status: str


class OverlayLayoutPatch(BaseModel):
    id: str
    layout: OverlayLayout


class CreativePlanStartRequest(BaseModel):
    """Optional user brief describing how to edit the video."""

    prompt: str | None = Field(default=None, max_length=4000)


class CreativePlanValidateRequest(BaseModel):
    accept_all: bool = False
    accept_overlay_ids: list[str] = Field(default_factory=list)
    reject_overlay_ids: list[str] = Field(default_factory=list)
    visual_style: VisualStyle | None = None
    captions_mode: CaptionStyle | None = None
    captions_position: CaptionPosition | None = None
    captions_scale: CaptionScale | None = None
    overlay_layouts: list[OverlayLayoutPatch] = Field(default_factory=list)


class CreativePlanOverlayAddRequest(BaseModel):
    """Add a user-uploaded or AI-generated overlay to the creative plan."""

    prompt: str = Field(default="User media", min_length=1, max_length=500)
    asset_url: str | None = Field(default=None, max_length=2000)
    layout: OverlayLayout = "plate"
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    generate: bool = False


class MediaAssetUploadResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    secure_url: str
    kind: Literal["image", "video", "other"] = "image"


class CreativePlanZoom(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    scale: float = Field(gt=1.0, le=5.0)


class CreativePlanPublic(BaseModel):
    video_id: str
    project_id: str
    edit_plan_id: str | None = None
    status: str
    visual_style: VisualStyle = "prism"
    captions_mode: CaptionStyle = "dynamic"
    captions_position: CaptionPosition = "lower"
    captions_scale: CaptionScale = "md"
    overlays: list[VisualOverlay] = Field(default_factory=list)
    timeline_segments: list[TimelineSegment] = Field(default_factory=list)
    zooms: list[CreativePlanZoom] = Field(default_factory=list)
    validated: bool = False


class EditPlanVersionItem(BaseModel):
    id: str
    label: str


class EditPlanPublic(ORMModel):
    id: str
    project_id: str
    source_video_id: str
    analysis_id: str | None
    job_id: str | None
    version: int
    prompt: str | None
    status: str
    plan: dict[str, Any]
    versions: list[EditPlanVersionItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EditPlanPutRequest(BaseModel):
    plan: EditPlanDocument


class EditPlanPatchRequest(BaseModel):
    timeline: Timeline | None = None
    operations: list[ZoomOperation | CropOperation] | None = None
    captions: CaptionsConfig | None = None
    visual_style: VisualStyle | None = None
    overlays: list[VisualOverlay] | None = None
    audio: AudioConfig | None = None
    output: OutputConfig | None = None
