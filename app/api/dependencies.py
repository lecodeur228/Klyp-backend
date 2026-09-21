"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import get_ai_provider
from app.ai.providers.base import AIProvider
from app.core.config import Settings, get_settings
from app.core.constants import ErrorCode
from app.core.exceptions import AuthenticationException, AuthorizationException
from app.core.security import decode_access_token, hash_token
from app.db.session import get_db
from app.i18n.messages import resolve_locale
from app.models.user import ApiKey, User
from app.services.auth.service import get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
AIProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]


async def get_locale(
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> str:
    cfg = get_settings()
    return resolve_locale(accept_language, cfg.default_locale)


LocaleDep = Annotated[str, Depends(get_locale)]


async def get_current_user(
    request: Request,
    session: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-KEY")] = None,
) -> User:
    if x_api_key:
        key_hash = hash_token(x_api_key)
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise AuthenticationException("Invalid API key", code=ErrorCode.INVALID_API_KEY)
        user = await get_user_by_id(session, api_key.user_id)
        if not user or not user.is_active:
            raise AuthenticationException("Invalid API key", code=ErrorCode.INVALID_API_KEY)
        request.state.auth_method = "api_key"
        return user

    if not credentials:
        raise AuthenticationException()

    try:
        payload = decode_access_token(credentials.credentials, settings)
    except jwt.PyJWTError as exc:
        raise AuthenticationException("Invalid token", code=ErrorCode.INVALID_TOKEN) from exc

    if payload.get("type") != "access":
        raise AuthenticationException("Invalid token", code=ErrorCode.INVALID_TOKEN)

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException("Invalid token", code=ErrorCode.INVALID_TOKEN)

    user = await get_user_by_id(session, str(user_id))
    if not user or not user.is_active:
        raise AuthenticationException()
    request.state.auth_method = "jwt"
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str) -> Any:
    async def _checker(user: CurrentUser) -> User:
        if permission not in user.permission_names and "admin" not in user.role_names:
            raise AuthorizationException()
        return user

    return _checker
