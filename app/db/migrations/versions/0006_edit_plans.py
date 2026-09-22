"""Add edit_plans table

Revision ID: 0006_edit_plans
Revises: 0005_analysis
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_edit_plans"
down_revision: str | None = "0005_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edit_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_video_id",
            sa.String(length=36),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analysis_id",
            sa.String(length=36),
            sa.ForeignKey("video_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", name="uq_edit_plans_project_id"),
    )
    op.create_index("ix_edit_plans_project_id", "edit_plans", ["project_id"])
    op.create_index("ix_edit_plans_source_video_id", "edit_plans", ["source_video_id"])
    op.create_index("ix_edit_plans_analysis_id", "edit_plans", ["analysis_id"])
    op.create_index("ix_edit_plans_job_id", "edit_plans", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_edit_plans_job_id", table_name="edit_plans")
    op.drop_index("ix_edit_plans_analysis_id", table_name="edit_plans")
    op.drop_index("ix_edit_plans_source_video_id", table_name="edit_plans")
    op.drop_index("ix_edit_plans_project_id", table_name="edit_plans")
    op.drop_table("edit_plans")
