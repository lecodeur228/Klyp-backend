"""Videos API tests."""

import io

import pytest
from httpx import AsyncClient


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Upload project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


@pytest.mark.asyncio
async def test_videos_upload_get_delete(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

    upload = await client.post(
        f"/api/v1/projects/{project_id}/videos",
        headers=auth_headers,
        files={"file": ("clip.mp4", io.BytesIO(fake_mp4), "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["success"] is True
    video_id = body["data"]["id"]
    assert body["data"]["project_id"] == project_id
    assert body["data"]["status"] == "ready"
    assert body["data"]["original_asset"]["filename"] == "clip.mp4"
    assert body["data"]["original_asset"]["size"] == len(fake_mp4)
    assert "projects/" in body["data"]["original_asset"]["public_id"]
    assert "originals" in body["data"]["original_asset"]["public_id"]

    detail = await client.get(f"/api/v1/videos/{video_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == video_id

    deleted = await client.delete(f"/api/v1/videos/{video_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True

    missing = await client.get(f"/api/v1/videos/{video_id}", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_videos_reject_non_video(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    response = await client.post(
        f"/api/v1/projects/{project_id}/videos",
        headers=auth_headers,
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_videos_require_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/videos/does-not-exist")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_videos_upload_unknown_project(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/videos",
        headers=auth_headers,
        files={"file": ("clip.mp4", io.BytesIO(fake_mp4), "video/mp4")},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
