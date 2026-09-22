"""Add renders table

Revision ID: 0008_renders
Revises: 0007_video_captions
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_renders"
down_revision: str | None = "0007_video_captions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "renders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "edit_plan_id",
            sa.String(length=36),
            sa.ForeignKey("edit_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_video_id",
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
        sa.Column(
            "output_asset_id",
            sa.String(length=36),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="export"),
        sa.Column("secure_url", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_renders_project_id", "renders", ["project_id"])
    op.create_index("ix_renders_user_id", "renders", ["user_id"])
    op.create_index("ix_renders_edit_plan_id", "renders", ["edit_plan_id"])
    op.create_index("ix_renders_source_video_id", "renders", ["source_video_id"])
    op.create_index("ix_renders_job_id", "renders", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_renders_job_id", table_name="renders")
    op.drop_index("ix_renders_source_video_id", table_name="renders")
    op.drop_index("ix_renders_edit_plan_id", table_name="renders")
    op.drop_index("ix_renders_user_id", table_name="renders")
    op.drop_index("ix_renders_project_id", table_name="renders")
    op.drop_table("renders")
