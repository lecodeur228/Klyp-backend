"""Pytest fixtures — in-memory SQLite for fast API tests."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AI_PROVIDER", "fake")
os.environ.setdefault("SECRET_KEY", "change-me-to-a-long-random-secret-key-at-least-32")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///:memory:")

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.seed import seed
from app.main import create_app
from app.models.user import Role, User

get_settings.cache_clear()


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as db:
        await seed(db)
        await db.commit()
        yield db
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    from app.db.session import get_db

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    user = User(
        email="demo@example.com",
        name="Demo",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    role = (await session.execute(select(Role).where(Role.name == "user"))).scalar_one()
    user.roles.append(role)
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "demo@example.com", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
