"""Auth service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.constants import ErrorCode
from app.core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    NotFoundException,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.user import RefreshToken, Role, User
from app.schemas.common import TokenPair, UserPublic


def to_user_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        roles=user.role_names,
        permissions=sorted(user.permission_names),
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.email == email.lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def register_user(
    session: AsyncSession,
    settings: Settings,
    *,
    name: str,
    email: str,
    password: str,
) -> TokenPair:
    existing = await get_user_by_email(session, email)
    if existing:
        raise ConflictException("Email already exists", code=ErrorCode.EMAIL_ALREADY_EXISTS)

    user = User(
        name=name,
        email=email.lower(),
        password_hash=hash_password(password),
        is_active=True,
    )
    role = (await session.execute(select(Role).where(Role.name == "user"))).scalar_one_or_none()
    if role:
        user.roles.append(role)
    session.add(user)
    await session.flush()
    return await issue_tokens(session, settings, user)


async def login_user(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    device_name: str | None = None,
) -> TokenPair:
    user = await get_user_by_email(session, email)
    if not user or not verify_password(password, user.password_hash):
        raise AuthenticationException("Invalid credentials")
    if not user.is_active:
        raise AuthorizationException("Account inactive", code=ErrorCode.ACCOUNT_INACTIVE)
    return await issue_tokens(session, settings, user, device_name=device_name)


async def issue_tokens(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    device_name: str | None = None,
) -> TokenPair:
    access = create_access_token(user.id, settings)
    raw_refresh = generate_refresh_token()
    refresh = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        device_name=device_name,
    )
    session.add(refresh)
    await session.flush()
    return TokenPair(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
        user=to_user_public(user),
    )


async def refresh_tokens(
    session: AsyncSession,
    settings: Settings,
    *,
    refresh_token: str,
) -> TokenPair:
    token_hash = hash_token(refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if not stored or stored.revoked_at is not None or stored.expires_at < now:
        raise AuthenticationException("Invalid token", code=ErrorCode.INVALID_TOKEN)

    stored.revoked_at = now
    user = await get_user_by_id(session, stored.user_id)
    if not user or not user.is_active:
        raise AuthenticationException("Invalid token", code=ErrorCode.INVALID_TOKEN)
    return await issue_tokens(session, settings, user, device_name=stored.device_name)


async def logout(session: AsyncSession, *, refresh_token: str) -> None:
    token_hash = hash_token(refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        await session.flush()


async def require_user(session: AsyncSession, user_id: str) -> User:
    user = await get_user_by_id(session, user_id)
    if not user:
        raise NotFoundException("User not found")
    if not user.is_active:
        raise AuthorizationException("Account inactive", code=ErrorCode.ACCOUNT_INACTIVE)
    return user
