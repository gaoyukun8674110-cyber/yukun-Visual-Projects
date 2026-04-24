from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, jobs, media, ws

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(media.router, prefix="/media", tags=["media"])
router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
router.include_router(ws.router, prefix="/ws", tags=["websocket"])
