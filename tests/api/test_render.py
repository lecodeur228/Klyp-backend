"""Render API tests."""

from __future__ import annotations

import io

import pytest
from app.render.ffmpeg import build_ffmpeg_command, output_size
from app.schemas.editplan import (
    EditPlanDocument,
    OutputConfig,
    Timeline,
    TimelineSegment,
)
from httpx import AsyncClient


async def _pipeline_to_edit_plan(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str]:
    project = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Render project"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["data"]["id"]

    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    upload = await client.post(
        f"/api/v1/projects/{project_id}/videos",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(fake_mp4), "video/mp4")},
    )
    video_id = upload.json()["data"]["id"]

    assert (
        await client.post(f"/api/v1/videos/{video_id}/analyze", headers=headers)
    ).status_code == 202

    assert (
        await client.post(
            f"/api/v1/videos/{video_id}/ai-edit",
            headers=headers,
            json={"prompt": "Vertical cut silence"},
        )
    ).status_code == 202

    return project_id, video_id


@pytest.mark.asyncio
async def test_render_flow(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id, _video_id = await _pipeline_to_edit_plan(client, auth_headers)

    started = await client.post(
        f"/api/v1/projects/{project_id}/render",
        headers=auth_headers,
        json={"kind": "export"},
    )
    assert started.status_code == 202, started.text
    body = started.json()["data"]
    assert body["render_id"]
    assert body["job_id"]
    assert body["status"] == "ready"

    job = await client.get(f"/api/v1/jobs/{body['job_id']}", headers=auth_headers)
    assert job.json()["data"]["type"] == "project.render"
    assert job.json()["data"]["status"] == "completed"
    assert job.json()["data"]["result"]["stub"] is True

    detail = await client.get(
        f"/api/v1/renders/{body['render_id']}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["status"] == "ready"
    assert data["secure_url"]
    assert data["output_asset_id"]


@pytest.mark.asyncio
async def test_render_requires_edit_plan(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "No plan"},
    )
    project_id = project.json()["data"]["id"]
    response = await client.post(
        f"/api/v1/projects/{project_id}/render",
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_edit_plan_render_alias(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id, _ = await _pipeline_to_edit_plan(client, auth_headers)
    response = await client.post(
        f"/api/v1/projects/{project_id}/edit-plan/render",
        headers=auth_headers,
        json={"kind": "preview"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["data"]["status"] == "ready"


def test_build_ffmpeg_command_argv() -> None:
    plan = EditPlanDocument(
        source_video_id="v1",
        timeline=Timeline(segments=[TimelineSegment(id="a", start=1.0, end=5.0)]),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
    )
    w, h = output_size(plan)
    assert (w, h) == (720, 1280)
    cmd = build_ffmpeg_command(
        input_path=__import__("pathlib").Path("/tmp/in.mp4"),
        output_path=__import__("pathlib").Path("/tmp/out.mp4"),
        plan=plan,
    )
    assert cmd[0] == "ffmpeg"
    joined = " ".join(cmd)
    assert "trim=start=1.0:end=5.0" in joined
    assert "-filter_complex" in cmd
    assert str(w) in joined
