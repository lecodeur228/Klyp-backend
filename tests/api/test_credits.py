"""Credits / payments API tests."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.models.credit_account import CreditAccount
from app.models.job import Job
from app.models.user import Role, User
from app.services.credits import service as credits_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import topup_credits


async def _register(client: AsyncClient, email: str = "broke@example.com") -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Broke", "email": email, "password": "password123"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Credits project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _upload_video(
    client: AsyncClient, headers: dict[str, str], project_id: str
) -> dict:
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    response = await client.post(
        f"/api/v1/projects/{project_id}/videos",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(fake_mp4), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_checkout_increases_balance_and_is_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    before = await client.get("/api/v1/credits", headers=auth_headers)
    assert before.status_code == 200
    start = before.json()["data"]["balance"]

    first = await client.post(
        "/api/v1/payments/checkout",
        headers=auth_headers,
        json={"credits": 50, "idempotency_key": "topup-once"},
    )
    assert first.status_code == 201, first.text
    payment_id = first.json()["data"]["id"]
    assert first.json()["data"]["status"] == "completed"
    assert first.json()["data"]["credits"] == 50

    mid = await client.get("/api/v1/credits", headers=auth_headers)
    assert mid.json()["data"]["balance"] == start + 50

    second = await client.post(
        "/api/v1/payments/checkout",
        headers=auth_headers,
        json={"credits": 50, "idempotency_key": "topup-once"},
    )
    assert second.status_code == 201
    assert second.json()["data"]["id"] == payment_id

    after = await client.get("/api/v1/credits", headers=auth_headers)
    assert after.json()["data"]["balance"] == start + 50

    got = await client.get(f"/api/v1/payments/{payment_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["data"]["id"] == payment_id


@pytest.mark.asyncio
async def test_estimate_analyze_positive(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video = await _upload_video(client, auth_headers, project_id)

    response = await client.post(
        "/api/v1/credits/estimate",
        headers=auth_headers,
        json={"operation": "video.analyze", "video_id": video["id"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["credits"] > 0
    assert data["breakdown"]["operation"] == "video.analyze"


@pytest.mark.asyncio
async def test_analyze_without_credits_returns_402(
    client: AsyncClient,
) -> None:
    headers = await _register(client, email="nocredits@example.com")
    project_id = await _create_project(client, headers)
    video = await _upload_video(client, headers, project_id)

    bal = await client.get("/api/v1/credits", headers=headers)
    assert bal.json()["data"]["balance"] == 0

    started = await client.post(
        f"/api/v1/videos/{video['id']}/analyze", headers=headers
    )
    assert started.status_code == 402, started.text
    assert started.json()["code"] == "INSUFFICIENT_CREDITS"

    analysis = await client.get(f"/api/v1/videos/{video['id']}/analysis", headers=headers)
    assert analysis.status_code == 404

    tx = await client.get("/api/v1/credits/transactions", headers=headers)
    assert tx.status_code == 200
    assert tx.json()["data"] == []


@pytest.mark.asyncio
async def test_topup_then_analyze_debits(
    client: AsyncClient,
) -> None:
    headers = await _register(client, email="spender@example.com")
    await topup_credits(client, headers, credits=100, idempotency_key="spend-1")

    before = (await client.get("/api/v1/credits", headers=headers)).json()["data"]["balance"]
    assert before == 100

    project_id = await _create_project(client, headers)
    video = await _upload_video(client, headers, project_id)

    estimate = await client.post(
        "/api/v1/credits/estimate",
        headers=headers,
        json={"operation": "video.analyze", "video_id": video["id"]},
    )
    cost = estimate.json()["data"]["credits"]

    started = await client.post(
        f"/api/v1/videos/{video['id']}/analyze", headers=headers
    )
    assert started.status_code == 202, started.text
    assert started.json()["data"]["job_id"]

    after = (await client.get("/api/v1/credits", headers=headers)).json()["data"]["balance"]
    assert after == before - cost

    txs = await client.get("/api/v1/credits/transactions", headers=headers)
    types = {t["type"] for t in txs.json()["data"]}
    assert "debit" in types
    assert "topup" in types


@pytest.mark.asyncio
async def test_cancel_queued_job_refunds(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Cancel a queued job that was debited → balance restored."""
    user = User(
        email="cancel@example.com",
        name="Cancel",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    role = (await session.execute(select(Role).where(Role.name == "user"))).scalar_one()
    user.roles.append(role)
    session.add(user)
    await session.flush()
    session.add(CreditAccount(user_id=user.id, balance=0))
    await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "cancel@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    await topup_credits(client, headers, credits=80, idempotency_key="cancel-topup")

    job_id = str(uuid4())
    await credits_service.require_and_debit(
        session,
        user_id=user.id,
        operation="video.analyze",
        amount=20,
        job_id=job_id,
    )
    session.add(
        Job(
            id=job_id,
            user_id=user.id,
            type="video.analyze",
            status="queued",
            progress=0,
            stage="queued",
        )
    )
    await session.commit()

    mid = (await client.get("/api/v1/credits", headers=headers)).json()["data"]["balance"]
    assert mid == 60

    cancelled = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"

    after = (await client.get("/api/v1/credits", headers=headers)).json()["data"]["balance"]
    assert after == 80

    # Idempotent second cancel should 409 (not queued anymore)
    again = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers)
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_webhook_returns_501(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/payments/webhook/stripe",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 501
