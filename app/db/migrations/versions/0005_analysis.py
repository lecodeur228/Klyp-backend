"""Add video_analyses table

Revision ID: 0005_analysis
Revises: 0004_jobs
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_analysis"
down_revision: str | None = "0004_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_analyses",
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
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("segments", sa.JSON(), nullable=True),
        sa.Column("vad_segments", sa.JSON(), nullable=True),
        sa.Column("fillers", sa.JSON(), nullable=True),
        sa.Column("scenes", sa.JSON(), nullable=True),
        sa.Column("faces", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("video_id", name="uq_video_analyses_video_id"),
    )
    op.create_index("ix_video_analyses_video_id", "video_analyses", ["video_id"])
    op.create_index("ix_video_analyses_job_id", "video_analyses", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_video_analyses_job_id", table_name="video_analyses")
    op.drop_index("ix_video_analyses_video_id", table_name="video_analyses")
    op.drop_table("video_analyses")
