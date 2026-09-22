"""Credits API routes."""

from fastapi import APIRouter

from app.api.dependencies import AppSettings, CurrentUser, DbSession, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate
from app.schemas.credits import CreditEstimateRequest
from app.schemas.pagination import build_meta
from app.services.credits import service as credits_service

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("")
async def get_balance(
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    balance = await credits_service.get_balance(session, user_id=user.id)
    return success_response(balance.model_dump(mode="json"), translate("ok", locale))


@router.get("/transactions")
async def list_transactions(
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    page: int = 1,
    per_page: int = 15,
):
    items, total = await credits_service.list_transactions(
        session, user_id=user.id, page=page, per_page=per_page
    )
    data = [credits_service.to_tx_public(t).model_dump(mode="json") for t in items]
    return success_response(
        data,
        translate("ok", locale),
        meta=build_meta(page=page, per_page=per_page, total=total),
    )


@router.post("/estimate")
async def estimate_credits(
    body: CreditEstimateRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    result = await credits_service.estimate(
        session,
        user_id=user.id,
        operation=body.operation,
        video_id=body.video_id,
        project_id=body.project_id,
        kind=body.kind,
        settings=settings,
    )
    return success_response(result.model_dump(mode="json"), translate("ok", locale))
