"""Captions API tests."""

from __future__ import annotations

import io

import pytest
from app.captions.build import build_cues
from httpx import AsyncClient


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Captions project"},
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
async def test_captions_flow(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video_id = await _upload_and_analyze(client, auth_headers, project_id)

    missing = await client.get(
        f"/api/v1/videos/{video_id}/captions", headers=auth_headers
    )
    assert missing.status_code == 404

    started = await client.post(
        f"/api/v1/videos/{video_id}/captions",
        headers=auth_headers,
        json={"style": "minimal"},
    )
    assert started.status_code == 202, started.text
    body = started.json()["data"]
    assert body["captions_id"]
    assert body["job_id"]
    assert body["status"] == "ready"

    job = await client.get(f"/api/v1/jobs/{body['job_id']}", headers=auth_headers)
    assert job.json()["data"]["type"] == "video.captions"
    assert job.json()["data"]["status"] == "completed"

    detail = await client.get(
        f"/api/v1/videos/{video_id}/captions", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["status"] == "ready"
    assert data["style"] == "minimal"
    assert len(data["cues"]) >= 1
    assert data["cues"][0]["text"]


@pytest.mark.asyncio
async def test_captions_require_analysis(
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
        f"/api/v1/videos/{video_id}/captions", headers=auth_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_patch_caption_text(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video_id = await _upload_and_analyze(client, auth_headers, project_id)
    await client.post(
        f"/api/v1/videos/{video_id}/captions",
        headers=auth_headers,
        json={"style": "minimal"},
    )
    detail = await client.get(
        f"/api/v1/videos/{video_id}/captions", headers=auth_headers
    )
    cues = detail.json()["data"]["cues"]
    cues[0]["text"] = "Texte édité"

    patched = await client.patch(
        f"/api/v1/videos/{video_id}/captions",
        headers=auth_headers,
        json={"cues": cues},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["cues"][0]["text"] == "Texte édité"


def test_build_cues_minimal_vs_dynamic() -> None:
    segments = [
        {
            "id": "seg-1",
            "start": 0.0,
            "end": 5.0,
            "text": "un deux trois quatre cinq six sept huit",
            "words": [
                {"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
                for i, w in enumerate(
                    ["un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit"]
                )
            ],
        }
    ]
    minimal = build_cues(segments, style="minimal")
    dynamic = build_cues(segments, style="dynamic")
    assert len(minimal) == 1
    assert len(dynamic) > len(minimal)
    assert dynamic[0]["words"]
