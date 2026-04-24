from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import HealthRead

router = APIRouter()


@router.get("/health", response_model=HealthRead)
async def health() -> HealthRead:
    return HealthRead(ok=True, service=get_settings().app_name)
