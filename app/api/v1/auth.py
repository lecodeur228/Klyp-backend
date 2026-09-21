"""Auth routes."""

from fastapi import APIRouter, Request

from app.api.dependencies import AppSettings, CurrentUser, DbSession, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest
from app.services.auth import service as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    session: DbSession,
    settings: AppSettings,
    locale: LocaleDep,
):
    tokens = await auth_service.register_user(
        session,
        settings,
        name=body.name,
        email=body.email,
        password=body.password,
    )
    return success_response(
        tokens.model_dump(),
        translate("register_success", locale),
        status_code=201,
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    session: DbSession,
    settings: AppSettings,
    locale: LocaleDep,
):
    tokens = await auth_service.login_user(
        session,
        settings,
        email=body.email,
        password=body.password,
        device_name=body.device_name,
    )
    return success_response(tokens.model_dump(), translate("login_success", locale))


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    session: DbSession,
    settings: AppSettings,
    locale: LocaleDep,
):
    tokens = await auth_service.refresh_tokens(
        session,
        settings,
        refresh_token=body.refresh_token,
    )
    return success_response(tokens.model_dump(), translate("ok", locale))


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    session: DbSession,
    locale: LocaleDep,
):
    await auth_service.logout(session, refresh_token=body.refresh_token)
    return success_response(None, translate("logout_success", locale))


@router.get("/me")
async def me(user: CurrentUser, locale: LocaleDep, request: Request):
    payload = auth_service.to_user_public(user).model_dump()
    payload["auth_method"] = getattr(request.state, "auth_method", None)
    return success_response(payload, translate("ok", locale))
