"""Analysis API tests."""

from __future__ import annotations

import io

import pytest
from app.analysis.providers.fake import FakeTranscriptionProvider
from app.models.analysis import VideoAnalysis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Analysis project"},
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
async def test_analyze_flow_ready_with_segments(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video = await _upload_video(client, auth_headers, project_id)
    video_id = video["id"]

    missing = await client.get(f"/api/v1/videos/{video_id}/analysis", headers=auth_headers)
    assert missing.status_code == 404

    started = await client.post(
        f"/api/v1/videos/{video_id}/analyze", headers=auth_headers
    )
    assert started.status_code == 202, started.text
    body = started.json()["data"]
    job_id = body["job_id"]
    assert body["analysis_id"]
    assert body["status"] == "ready"  # inline in test env

    job = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
    assert job.status_code == 200
    assert job.json()["data"]["status"] == "completed"
    assert job.json()["data"]["type"] == "video.analyze"

    analysis = await client.get(
        f"/api/v1/videos/{video_id}/analysis", headers=auth_headers
    )
    assert analysis.status_code == 200, analysis.text
    data = analysis.json()["data"]
    assert data["status"] == "ready"
    assert data["language"] == "fr"
    assert len(data["segments"]) >= 1
    assert data["segments"][0]["words"]
    assert isinstance(data["vad_segments"], list)
    assert isinstance(data["fillers"], list)
    assert data["scenes"] == []
    assert data["faces"] == []


@pytest.mark.asyncio
async def test_analyze_conflict_when_processing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session: AsyncSession,
) -> None:
    project_id = await _create_project(client, auth_headers)
    video = await _upload_video(client, auth_headers, project_id)

    analysis = VideoAnalysis(
        video_id=video["id"],
        status="processing",
        segments=[],
        vad_segments=[],
        fillers=[],
        scenes=[],
        faces=[],
    )
    session.add(analysis)
    await session.commit()

    response = await client.post(
        f"/api/v1/videos/{video['id']}/analyze", headers=auth_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_analyze_unknown_video(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/videos/00000000-0000-0000-0000-000000000000/analyze",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reanalyze_when_ready(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _create_project(client, auth_headers)
    video = await _upload_video(client, auth_headers, project_id)
    video_id = video["id"]

    first = await client.post(f"/api/v1/videos/{video_id}/analyze", headers=auth_headers)
    assert first.status_code == 202
    first_id = first.json()["data"]["analysis_id"]

    second = await client.post(f"/api/v1/videos/{video_id}/analyze", headers=auth_headers)
    assert second.status_code == 202
    assert second.json()["data"]["analysis_id"] == first_id
    assert second.json()["data"]["status"] == "ready"


def test_fake_transcription_timestamps_within_duration() -> None:
    provider = FakeTranscriptionProvider()
    result = provider.transcribe(duration=12.0, language="fr")
    assert result.language == "fr"
    assert len(result.segments) == 3
    assert result.fillers  # euh / um in phrases
    assert result.vad_segments
    prev_end = 0.0
    for seg in result.segments:
        assert seg.start >= prev_end - 0.001
        assert seg.end <= 12.0 + 0.001
        assert seg.words
        for word in seg.words:
            assert word.start >= seg.start - 0.001
            assert word.end <= seg.end + 0.001
            assert word.start <= word.end
        prev_end = seg.start
