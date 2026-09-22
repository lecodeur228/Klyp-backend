"""Payments API routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.dependencies import AppSettings, CurrentUser, DbSession, LocaleDep
from app.core.responses import error_response, success_response
from app.i18n.messages import translate
from app.schemas.payments import CheckoutRequest
from app.services.payments import service as payments_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/checkout", status_code=201)
async def checkout(
    body: CheckoutRequest,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
    settings: AppSettings,
):
    payment = await payments_service.checkout_stub(
        session, user_id=user.id, body=body, settings=settings
    )
    return success_response(
        payments_service.to_public(payment).model_dump(mode="json"),
        translate("payment_completed", locale),
        status_code=201,
    )


@router.get("/{payment_id}")
async def get_payment(
    payment_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payment = await payments_service.get_owned_payment(
        session, user_id=user.id, payment_id=payment_id
    )
    return success_response(
        payments_service.to_public(payment).model_dump(mode="json"),
        translate("ok", locale),
    )


@router.post("/webhook/{provider}")
async def payment_webhook(provider: str) -> JSONResponse:
    """Real provider webhooks deferred past Sprint G."""
    return error_response(
        message=f"Webhook for provider '{provider}' not implemented",
        code="NOT_IMPLEMENTED",
        status_code=501,
    )
