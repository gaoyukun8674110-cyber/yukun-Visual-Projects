from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_api_key
from app.db import get_session
from app.models import DetectionJob, MediaAsset

router = APIRouter()


def _resolve_storage_path(file_path: str) -> tuple[Path, str]:
    settings = get_settings()
    storage_root = settings.storage_root.resolve()
    candidate = (storage_root / file_path).resolve()

    try:
        relative = candidate.relative_to(storage_root).as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return candidate, relative


async def _client_owns_path(session: AsyncSession, client_id: str, relative_path: str) -> bool:
    media_result = await session.execute(
        select(MediaAsset.id).where(
            MediaAsset.storage_path == relative_path,
            MediaAsset.client_id == client_id,
        )
    )
    if media_result.scalar_one_or_none() is not None:
        return True

    job_result = await session.execute(
        select(DetectionJob.id).where(
            DetectionJob.result_path == relative_path,
            DetectionJob.client_id == client_id,
        )
    )
    return job_result.scalar_one_or_none() is not None


@router.get("/{file_path:path}")
async def download_file(
    file_path: str,
    client_id: str = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    absolute_path, relative_path = _resolve_storage_path(file_path)
    if not await _client_owns_path(session, client_id, relative_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(absolute_path)
