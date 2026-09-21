"""API smoke tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_me(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "password123",
        },
        headers={"Accept-Language": "en"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["success"] is True
    assert "access_token" in body["data"]

    token = body["data"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_login_validation_error(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "bad", "password": "x"})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_ai_generate_with_auth(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/ai/generate",
        headers=auth_headers,
        json={"prompt": "Say hello"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["provider"] == "fake"
    assert "Say hello" in body["data"]["content"]


@pytest.mark.asyncio
async def test_ai_job_accepted(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/ai/jobs",
        headers=auth_headers,
        json={"prompt": "Heavy task", "type": "generate"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["success"] is True
    job_id = body["data"]["id"]

    detail = await client.get(f"/api/v1/ai/jobs/{job_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == job_id


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    # DB is overridden/sqlite — health may report redis degraded
    assert response.status_code in (200, 503)
    assert "success" in response.json()
