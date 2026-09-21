"""Users routes (authorization example)."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, DbSession, LocaleDep, require_permission
from app.core.responses import success_response
from app.i18n.messages import translate
from app.models.user import User
from app.schemas.pagination import build_meta
from app.services.auth.service import to_user_public

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(
    session: DbSession,
    locale: LocaleDep,
    _: User = Depends(require_permission("users.manage")),
    page: int = 1,
    per_page: int = 15,
):
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    result = await session.execute(
        select(User).order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    users = result.scalars().all()
    data = [to_user_public(u).model_dump() for u in users]
    return success_response(
        data,
        translate("ok", locale),
        meta=build_meta(page=page, per_page=per_page, total=total),
    )


@router.get("/me-permissions")
async def my_permissions(user: CurrentUser, locale: LocaleDep):
    return success_response(
        {
            "roles": user.role_names,
            "permissions": sorted(user.permission_names),
        },
        translate("ok", locale),
    )
