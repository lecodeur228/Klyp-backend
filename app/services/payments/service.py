"""Payments service — stub checkout that credits the wallet."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundException, ValidationException
from app.models.payment import Payment
from app.schemas.payments import CheckoutRequest, PaymentPublic
from app.services.credits import service as credits_service


def to_public(payment: Payment) -> PaymentPublic:
    return PaymentPublic(
        id=payment.id,
        status=payment.status,
        credits=payment.credits,
        provider=payment.provider,
        idempotency_key=payment.idempotency_key,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


async def get_owned_payment(
    session: AsyncSession,
    *,
    user_id: str,
    payment_id: str,
) -> Payment:
    result = await session.execute(
        select(Payment).where(Payment.id == payment_id, Payment.user_id == user_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise NotFoundException("Payment not found")
    return payment


async def checkout_stub(
    session: AsyncSession,
    *,
    user_id: str,
    body: CheckoutRequest,
    settings: Settings | None = None,
) -> Payment:
    settings = settings or get_settings()
    if body.credits <= 0:
        raise ValidationException("credits must be positive")

    existing = (
        await session.execute(
            select(Payment).where(
                Payment.user_id == user_id,
                Payment.idempotency_key == body.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    await credits_service.ensure_account(session, user_id=user_id)

    payment = Payment(
        user_id=user_id,
        status="completed",
        credits=body.credits,
        provider=settings.payment_provider,
        idempotency_key=body.idempotency_key,
        external_ref=f"stub:{body.idempotency_key}",
    )
    session.add(payment)
    await session.flush()

    await credits_service.credit_topup(
        session,
        user_id=user_id,
        amount=body.credits,
        payment_id=payment.id,
        idempotency_key=f"topup:{body.idempotency_key}",
    )
    await session.refresh(payment)
    return payment
