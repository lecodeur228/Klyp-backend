"""API v1 router."""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    credits,
    files,
    health,
    jobs,
    payments,
    presets,
    projects,
    renders,
    sounds,
    users,
    videos,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(videos.router)
api_router.include_router(renders.router)
api_router.include_router(jobs.router)
api_router.include_router(credits.router)
api_router.include_router(payments.router)
api_router.include_router(ai.router)
api_router.include_router(files.router)
api_router.include_router(sounds.router)
api_router.include_router(presets.router)
