"""Jobs API tests."""

from __future__ import annotations

import io

import pytest
from app.core.security import hash_password
from app.models.job import Job
from app.models.user import Role, User
from app.services.jobs.service import to_progress_event
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Jobs project"},
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
async def test_upload_enqueues_post_process_job_completed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video = await _upload_video(client, auth_headers, project_id)
    job_id = video["post_process_job_id"]
    assert job_id

    detail = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()["data"]
    assert body["id"] == job_id
    assert body["type"] == "video.post_process"
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["stage"] == "done"
    assert body["video_id"] == video["id"]
    assert body["project_id"] == project_id


@pytest.mark.asyncio
async def test_cancel_queued_job(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session: AsyncSession,
) -> None:
    user = (
        await session.execute(select(User).where(User.email == "demo@example.com"))
    ).scalar_one()
    job = Job(
        user_id=user.id,
        type="video.post_process",
        status="queued",
        progress=0,
        stage="queued",
    )
    session.add(job)
    await session.commit()

    cancelled = await client.post(f"/api/v1/jobs/{job.id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text
    data = cancelled.json()["data"]
    assert data["status"] == "cancelled"
    assert data["stage"] == "cancelled"

    again = await client.post(f"/api/v1/jobs/{job.id}/cancel", headers=auth_headers)
    assert again.status_code == 409
    assert again.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_jobs_ownership_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session: AsyncSession,
) -> None:
    other = User(
        email="other@example.com",
        name="Other",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    role = (await session.execute(select(Role).where(Role.name == "user"))).scalar_one()
    other.roles.append(role)
    session.add(other)
    await session.flush()

    job = Job(
        user_id=other.id,
        type="video.post_process",
        status="queued",
        progress=0,
        stage="queued",
    )
    session.add(job)
    await session.commit()

    response = await client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_jobs_require_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/jobs/does-not-exist")
    assert response.status_code == 401


def test_to_progress_event_shape() -> None:
    job = Job(
        id="job-1",
        user_id="u1",
        type="video.post_process",
        status="processing",
        progress=50,
        stage="thumbnail",
        error_code=None,
    )
    event = to_progress_event(job)
    assert event.model_dump() == {
        "id": "job-1",
        "status": "processing",
        "progress": 50,
        "stage": "thumbnail",
        "error_code": None,
    }
