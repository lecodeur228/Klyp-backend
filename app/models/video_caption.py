"""Video captions domain model — timed cues per video."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

JSONType = JSON().with_variant(JSONB(), "postgresql")


class VideoCaption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "video_captions"
    __table_args__ = (UniqueConstraint("video_id", name="uq_video_captions_video_id"),)

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
    style: Mapped[str] = mapped_column(String(32), nullable=False, default="minimal")
    language: Mapped[str | None] = mapped_column(String(16))
    cues: Mapped[list[Any] | None] = mapped_column(JSONType)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
