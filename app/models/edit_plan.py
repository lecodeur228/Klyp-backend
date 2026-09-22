"""EditPlan persistence — one current plan per project."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

JSONType = JSON().with_variant(JSONB(), "postgresql")


class EditPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "edit_plans"
    __table_args__ = (UniqueConstraint("project_id", name="uq_edit_plans_project_id"),)

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    analysis_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("video_analyses.id", ondelete="SET NULL"),
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
