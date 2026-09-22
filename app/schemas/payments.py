"""Payments API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CheckoutRequest(BaseModel):
    credits: int = Field(..., gt=0)
    idempotency_key: str = Field(..., min_length=1, max_length=128)


class PaymentPublic(ORMModel):
    id: str
    status: str
    credits: int
    provider: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
