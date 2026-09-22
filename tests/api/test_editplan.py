"""EditPlan / AI Edit API tests."""

from __future__ import annotations

import io

import pytest
from app.core.exceptions import EditPlanInvalidException
from app.editplan.validation import (
    ensure_valid_edit_plan,
    repair_edit_plan,
    validate_edit_plan,
)
from app.schemas.editplan import (
    EditPlanDocument,
    OutputConfig,
    Timeline,
    TimelineSegment,
)
from app.services.editplan.service import build_fake_edit_plan
from httpx import AsyncClient
from pydantic import ValidationError


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "EditPlan project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _upload_and_analyze(
    client: AsyncClient, headers: dict[str, str], project_id: str
) -> str:
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    upload = await client.post(
        f"/api/v1/projects/{project_id}/videos",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(fake_mp4), "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    video_id = upload.json()["data"]["id"]

    analyzed = await client.post(
        f"/api/v1/videos/{video_id}/analyze", headers=headers
    )
    assert analyzed.status_code == 202, analyzed.text
    return video_id


@pytest.mark.asyncio
async def test_ai_edit_flow_and_get_plan(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video_id = await _upload_and_analyze(client, auth_headers, project_id)

    started = await client.post(
        f"/api/v1/videos/{video_id}/ai-edit",
        headers=auth_headers,
        json={"prompt": "Coupe les silences et mets en vertical"},
    )
    assert started.status_code == 202, started.text
    body = started.json()["data"]
    assert body["job_id"]
    assert body["edit_plan_id"]
    assert body["status"] == "ready"

    job = await client.get(f"/api/v1/jobs/{body['job_id']}", headers=auth_headers)
    assert job.status_code == 200
    assert job.json()["data"]["status"] == "completed"
    assert job.json()["data"]["type"] == "ai_edit"

    plan = await client.get(
        f"/api/v1/projects/{project_id}/edit-plan", headers=auth_headers
    )
    assert plan.status_code == 200, plan.text
    data = plan.json()["data"]
    assert data["status"] == "ready"
    assert data["version"] >= 1
    assert data["plan"]["timeline"]["segments"]
    assert data["plan"]["output"]["aspect_ratio"] == "9:16"
    assert data["versions"]


@pytest.mark.asyncio
async def test_ai_edit_requires_analysis(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
    upload = await client.post(
        f"/api/v1/projects/{project_id}/videos",
        headers=auth_headers,
        files={"file": ("clip.mp4", io.BytesIO(fake_mp4), "video/mp4")},
    )
    video_id = upload.json()["data"]["id"]

    response = await client.post(
        f"/api/v1/videos/{video_id}/ai-edit",
        headers=auth_headers,
        json={"prompt": "Edit please"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_put_invalid_edit_plan(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video_id = await _upload_and_analyze(client, auth_headers, project_id)
    await client.post(
        f"/api/v1/videos/{video_id}/ai-edit",
        headers=auth_headers,
        json={"prompt": "base"},
    )

    invalid = {
        "plan": {
            "schema_version": "1.0.0",
            "source_video_id": video_id,
            "timeline": {
                "segments": [
                    {"id": "a", "start": 0, "end": 10},
                    {"id": "b", "start": 5, "end": 15},
                ]
            },
            "operations": [],
            "captions": {"enabled": True, "style": "minimal"},
            "audio": {"denoise": False, "normalize": False},
            "output": {"resolution": "720p", "aspect_ratio": "9:16"},
        }
    }
    response = await client.put(
        f"/api/v1/projects/{project_id}/edit-plan",
        headers=auth_headers,
        json=invalid,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "EDIT_PLAN_INVALID"


@pytest.mark.asyncio
async def test_patch_audio_denoise(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video_id = await _upload_and_analyze(client, auth_headers, project_id)
    await client.post(
        f"/api/v1/videos/{video_id}/ai-edit",
        headers=auth_headers,
        json={"prompt": "base"},
    )

    patched = await client.patch(
        f"/api/v1/projects/{project_id}/edit-plan",
        headers=auth_headers,
        json={"audio": {"denoise": False, "normalize": True}},
    )
    assert patched.status_code == 200, patched.text
    audio = patched.json()["data"]["plan"]["audio"]
    assert audio["denoise"] is False
    assert audio["normalize"] is True
    assert patched.json()["data"]["version"] >= 2


def test_build_fake_edit_plan_valid() -> None:
    plan = build_fake_edit_plan(
        source_video_id="vid-1",
        duration=20.0,
        vad_segments=[{"start": 5.0, "end": 6.0, "kind": "silence"}],
        prompt="denoise please",
    )
    validated = validate_edit_plan(plan, duration=20.0)
    assert validated.timeline.segments
    assert validated.audio.denoise is True


def test_validate_edit_plan_rejects_bad_cases() -> None:
    base = EditPlanDocument(
        source_video_id="v1",
        timeline=Timeline(
            segments=[
                TimelineSegment(id="a", start=0, end=5),
                TimelineSegment(id="b", start=4, end=8),
            ]
        ),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
    )
    with pytest.raises(EditPlanInvalidException) as overlap:
        validate_edit_plan(base, duration=20.0)
    assert overlap.value.code.value == "EDIT_PLAN_INVALID"

    neg = EditPlanDocument(
        source_video_id="v1",
        timeline=Timeline(segments=[TimelineSegment(id="a", start=5, end=5)]),
    )
    with pytest.raises(EditPlanInvalidException):
        validate_edit_plan(neg, duration=20.0)

    raw = EditPlanDocument(
        source_video_id="v1",
        timeline=Timeline(segments=[TimelineSegment(id="a", start=0, end=5)]),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
    ).model_dump()
    raw["output"]["aspect_ratio"] = "21:9"
    with pytest.raises(ValidationError):
        EditPlanDocument.model_validate(raw)


def test_repair_and_ensure_valid_edit_plan() -> None:
    messy = EditPlanDocument(
        source_video_id="v1",
        timeline=Timeline(
            segments=[
                TimelineSegment(id="a", start=0, end=5),
                TimelineSegment(id="b", start=4, end=25),  # overlap + past duration
            ]
        ),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
    )
    repaired = repair_edit_plan(messy, duration=20.0)
    validated = validate_edit_plan(repaired, duration=20.0)
    assert validated.timeline.segments
    assert validated.timeline.segments[-1].end <= 20.0 + 1e-6

    empty = EditPlanDocument(
        source_video_id="v1",
        timeline=Timeline(segments=[]),
        output=OutputConfig(resolution="720p", aspect_ratio="9:16"),
    )
    ensured = ensure_valid_edit_plan(empty, duration=12.0)
    assert len(ensured.timeline.segments) >= 1
    assert ensured.timeline.segments[0].start == 0.0
    assert ensured.timeline.segments[0].end == 12.0
