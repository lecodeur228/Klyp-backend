"""Add video_captions table

Revision ID: 0007_video_captions
Revises: 0006_edit_plans
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_video_captions"
down_revision: str | None = "0006_edit_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_captions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "video_id",
            sa.String(length=36),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("style", sa.String(length=32), nullable=False, server_default="minimal"),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("cues", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("video_id", name="uq_video_captions_video_id"),
    )
    op.create_index("ix_video_captions_video_id", "video_captions", ["video_id"])
    op.create_index("ix_video_captions_job_id", "video_captions", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_video_captions_job_id", table_name="video_captions")
    op.drop_index("ix_video_captions_video_id", table_name="video_captions")
    op.drop_table("video_captions")
