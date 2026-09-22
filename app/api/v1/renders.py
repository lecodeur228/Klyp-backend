"""Renders API routes."""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession, LocaleDep
from app.core.responses import success_response
from app.i18n.messages import translate
from app.services.render import service as render_service

router = APIRouter(prefix="/renders", tags=["renders"])


@router.get("/{render_id}")
async def get_render(
    render_id: str,
    session: DbSession,
    user: CurrentUser,
    locale: LocaleDep,
):
    payload = await render_service.get_render_public(
        session, user_id=user.id, render_id=render_id
    )
    return success_response(payload.model_dump(mode="json"), translate("ok", locale))
