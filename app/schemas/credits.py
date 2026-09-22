"""Credits API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CreditBalancePublic(BaseModel):
    balance: int


class CreditTransactionPublic(ORMModel):
    id: str
    type: str
    amount: int
    balance_after: int
    job_id: str | None = None
    payment_id: str | None = None
    operation: str | None = None
    idempotency_key: str | None = None
    created_at: datetime


class CreditEstimateRequest(BaseModel):
    operation: Literal["video.analyze", "ai_edit", "project.render"]
    video_id: str | None = None
    project_id: str | None = None
    kind: Literal["preview", "export"] | None = None


class CreditEstimateResponse(BaseModel):
    credits: int
    breakdown: dict[str, Any] = Field(default_factory=dict)
