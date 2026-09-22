"""Projects API tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_projects_crud(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    create = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "My first edit", "description": "TikTok cut"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["success"] is True
    project_id = body["data"]["id"]
    assert body["data"]["name"] == "My first edit"
    assert body["data"]["status"] == "active"

    listed = await client.get("/api/v1/projects", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] >= 1
    assert any(p["id"] == project_id for p in listed.json()["data"])

    detail = await client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == project_id

    updated = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers,
        json={"name": "Renamed", "status": "archived"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Renamed"
    assert updated.json()["data"]["status"] == "archived"

    deleted = await client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True

    missing = await client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_projects_require_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
