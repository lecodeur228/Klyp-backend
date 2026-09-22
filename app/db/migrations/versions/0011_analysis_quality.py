"""Add analysis quality_warning for ASR sync QA

Revision ID: 0011_analysis_quality
Revises: 0010_user_onboarding
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_analysis_quality"
down_revision: str | None = "0010_user_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_analyses",
        sa.Column("quality_warning", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "video_analyses",
        sa.Column("aligned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("video_analyses", "aligned")
    op.drop_column("video_analyses", "quality_warning")
