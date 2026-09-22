"""Import all models for Alembic metadata."""

from app.models import (  # noqa: F401
    AiJob,
    AiUsage,
    ApiKey,
    Asset,
    CreditAccount,
    CreditTransaction,
    EditPlan,
    Job,
    Payment,
    Permission,
    Project,
    RefreshToken,
    Render,
    Role,
    User,
    Video,
    VideoAnalysis,
    VideoCaption,
)
from app.models.base import Base

__all__ = ["Base"]
