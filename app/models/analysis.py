"""Video analysis domain model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

JSONType = JSON().with_variant(JSONB(), "postgresql")


class VideoAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "video_analyses"
    __table_args__ = (UniqueConstraint("video_id", name="uq_video_analyses_video_id"),)

    video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    language: Mapped[str | None] = mapped_column(String(16))
    segments: Mapped[list[Any] | None] = mapped_column(JSONType)
    vad_segments: Mapped[list[Any] | None] = mapped_column(JSONType)
    fillers: Mapped[list[Any] | None] = mapped_column(JSONType)
    scenes: Mapped[list[Any] | None] = mapped_column(JSONType)
    faces: Mapped[list[Any] | None] = mapped_column(JSONType)
    quality_warning: Mapped[str | None] = mapped_column(String(255))
    aligned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
