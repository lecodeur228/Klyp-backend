"""WebSocket job progress endpoint."""

from __future__ import annotations

import asyncio

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.job import Job
from app.services.jobs.service import TERMINAL_STATUSES, to_progress_event

router = APIRouter()


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(
    websocket: WebSocket,
    job_id: str,
    token: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> None:
    settings = get_settings()
    try:
        payload = decode_access_token(token, settings)
    except jwt.PyJWTError:
        await websocket.close(code=4401)
        return

    if payload.get("type") != "access" or not payload.get("sub"):
        await websocket.close(code=4401)
        return

    user_id = str(payload["sub"])
    await websocket.accept()

    poll_seconds = 0.05 if settings.app_env == "test" else 1.0
    try:
        while True:
            result = await session.execute(
                select(Job).where(Job.id == job_id, Job.user_id == user_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                await websocket.send_json({"error": "NOT_FOUND", "message": "Job not found"})
                await websocket.close(code=4404)
                return

            event = to_progress_event(job).model_dump(mode="json")
            await websocket.send_json(event)
            if job.status in TERMINAL_STATUSES:
                await websocket.close()
                return

            await asyncio.sleep(poll_seconds)
    except WebSocketDisconnect:
        return
