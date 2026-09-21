"""API v1 router."""

from fastapi import APIRouter

from app.api.v1 import ai, auth, files, health, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(ai.router)
api_router.include_router(files.router)
