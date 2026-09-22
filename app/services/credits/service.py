"""Credit wallet service — estimate, debit, refund, topup ledger."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import InsufficientCreditsException, NotFoundException, ValidationException
from app.credits import pricing
from app.models.asset import Asset
from app.models.credit_account import CreditAccount
from app.models.credit_transaction import CreditTransaction
from app.models.edit_plan import EditPlan
from app.models.project import Project
from app.models.video import Video
from app.schemas.credits import (
    CreditBalancePublic,
    CreditEstimateResponse,
    CreditTransactionPublic,
)

Operation = Literal["video.analyze", "ai_edit", "project.render"]


def to_tx_public(tx: CreditTransaction) -> CreditTransactionPublic:
    return CreditTransactionPublic(
        id=tx.id,
        type=tx.type,
        amount=tx.amount,
        balance_after=tx.balance_after,
        job_id=tx.job_id,
        payment_id=tx.payment_id,
        operation=tx.operation,
        idempotency_key=tx.idempotency_key,
        created_at=tx.created_at,
    )


async def ensure_account(session: AsyncSession, *, user_id: str) -> CreditAccount:
    result = await session.execute(
        select(CreditAccount).where(CreditAccount.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if account:
        return account
    account = CreditAccount(user_id=user_id, balance=0)
    session.add(account)
    await session.flush()
    return account


async def get_account_for_update(session: AsyncSession, *, user_id: str) -> CreditAccount:
    result = await session.execute(
        select(CreditAccount)
        .where(CreditAccount.user_id == user_id)
        .with_for_update()
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = CreditAccount(user_id=user_id, balance=0)
        session.add(account)
        await session.flush()
        result = await session.execute(
            select(CreditAccount)
            .where(CreditAccount.user_id == user_id)
            .with_for_update()
        )
        account = result.scalar_one()
    return account


async def get_balance(session: AsyncSession, *, user_id: str) -> CreditBalancePublic:
    account = await ensure_account(session, user_id=user_id)
    return CreditBalancePublic(balance=account.balance)


async def list_transactions(
    session: AsyncSession,
    *,
    user_id: str,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list[CreditTransaction], int]:
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    total = (
        await session.execute(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
        )
    ).scalar_one()
    result = await session.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.scalars().all()), int(total)


async def _find_by_idempotency(
    session: AsyncSession,
    *,
    user_id: str,
    idempotency_key: str,
) -> CreditTransaction | None:
    result = await session.execute(
        select(CreditTransaction).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def credit_topup(
    session: AsyncSession,
    *,
    user_id: str,
    amount: int,
    payment_id: str | None = None,
    idempotency_key: str,
) -> CreditTransaction:
    if amount <= 0:
        raise ValidationException("Topup amount must be positive")

    existing = await _find_by_idempotency(
        session, user_id=user_id, idempotency_key=idempotency_key
    )
    if existing:
        return existing

    account = await get_account_for_update(session, user_id=user_id)
    account.balance += amount
    tx = CreditTransaction(
        user_id=user_id,
        type="topup",
        amount=amount,
        balance_after=account.balance,
        payment_id=payment_id,
        operation="topup",
        idempotency_key=idempotency_key,
    )
    session.add(tx)
    await session.flush()
    return tx


async def require_and_debit(
    session: AsyncSession,
    *,
    user_id: str,
    operation: str,
    amount: int,
    job_id: str,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    if amount <= 0:
        raise ValidationException("Debit amount must be positive")

    key = idempotency_key or f"debit:{job_id}"
    existing = await _find_by_idempotency(session, user_id=user_id, idempotency_key=key)
    if existing:
        return existing

    account = await get_account_for_update(session, user_id=user_id)
    if account.balance < amount:
        raise InsufficientCreditsException(
            f"Insufficient credits: need {amount}, have {account.balance}"
        )

    account.balance -= amount
    tx = CreditTransaction(
        user_id=user_id,
        type="debit",
        amount=amount,
        balance_after=account.balance,
        job_id=job_id,
        operation=operation,
        idempotency_key=key,
    )
    session.add(tx)
    await session.flush()
    return tx


async def refund_job(session: AsyncSession, *, job_id: str) -> CreditTransaction | None:
    """Refund debit linked to a job. Idempotent via key refund:{job_id}."""
    debit = (
        await session.execute(
            select(CreditTransaction).where(
                CreditTransaction.job_id == job_id,
                CreditTransaction.type == "debit",
            )
        )
    ).scalar_one_or_none()
    if not debit:
        return None

    key = f"refund:{job_id}"
    existing = await _find_by_idempotency(
        session, user_id=debit.user_id, idempotency_key=key
    )
    if existing:
        return existing

    account = await get_account_for_update(session, user_id=debit.user_id)
    account.balance += debit.amount
    tx = CreditTransaction(
        user_id=debit.user_id,
        type="refund",
        amount=debit.amount,
        balance_after=account.balance,
        job_id=job_id,
        operation=debit.operation,
        idempotency_key=key,
    )
    session.add(tx)
    await session.flush()
    return tx


async def _owned_video(
    session: AsyncSession, *, user_id: str, video_id: str
) -> Video:
    result = await session.execute(
        select(Video)
        .join(Project, Video.project_id == Project.id)
        .where(Video.id == video_id, Project.user_id == user_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise NotFoundException("Video not found")
    return video


async def _duration_for_video(session: AsyncSession, *, video: Video) -> float | None:
    result = await session.execute(
        select(Asset.duration).where(Asset.id == video.original_asset_id)
    )
    return result.scalar_one_or_none()


async def estimate(
    session: AsyncSession,
    *,
    user_id: str,
    operation: Operation,
    video_id: str | None = None,
    project_id: str | None = None,
    kind: Literal["preview", "export"] | None = None,
    settings: Settings | None = None,
) -> CreditEstimateResponse:
    settings = settings or get_settings()
    duration: float | None = None
    breakdown: dict[str, Any]

    if operation == "video.analyze":
        if not video_id:
            raise ValidationException("video_id is required for video.analyze")
        video = await _owned_video(session, user_id=user_id, video_id=video_id)
        duration = await _duration_for_video(session, video=video)
        credits, breakdown = pricing.estimate_analyze(settings, duration_seconds=duration)

    elif operation == "ai_edit":
        if not video_id:
            raise ValidationException("video_id is required for ai_edit")
        video = await _owned_video(session, user_id=user_id, video_id=video_id)
        duration = await _duration_for_video(session, video=video)
        credits, breakdown = pricing.estimate_ai_edit(settings, duration_seconds=duration)

    elif operation == "project.render":
        if not project_id:
            raise ValidationException("project_id is required for project.render")
        project = (
            await session.execute(
                select(Project).where(Project.id == project_id, Project.user_id == user_id)
            )
        ).scalar_one_or_none()
        if not project:
            raise NotFoundException("Project not found")
        edit_plan = (
            await session.execute(select(EditPlan).where(EditPlan.project_id == project_id))
        ).scalar_one_or_none()
        if not edit_plan:
            raise NotFoundException("EditPlan not found for project")
        video = await _owned_video(
            session, user_id=user_id, video_id=edit_plan.source_video_id
        )
        duration = await _duration_for_video(session, video=video)
        credits, breakdown = pricing.estimate_render(
            settings,
            duration_seconds=duration,
            kind=kind or "export",
        )
    else:
        raise ValidationException(f"Unknown operation: {operation}")

    return CreditEstimateResponse(credits=credits, breakdown=breakdown)
