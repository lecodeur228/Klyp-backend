"""Add user onboarding profile fields

Revision ID: 0010_user_onboarding
Revises: 0009_credits
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_user_onboarding"
down_revision: str | None = "0009_credits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("profession", sa.String(length=120), nullable=True))
    op.add_column(
        "users", sa.Column("referral_source", sa.String(length=120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "referral_source")
    op.drop_column("users", "profession")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
