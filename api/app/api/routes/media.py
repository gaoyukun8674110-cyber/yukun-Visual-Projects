from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import MediaAsset
from app.schemas import MediaAssetRead
from app.services.storage import save_upload

router = APIRouter()


@router.post("", response_model=MediaAssetRead, status_code=201)
async def upload_media(file: UploadFile, session: AsyncSession = Depends(get_session)) -> MediaAssetRead:
    storage_path, kind, file_size, digest = await save_upload(file)
    asset = MediaAsset(
        original_filename=file.filename or "upload",
        media_type=kind,
        content_type=file.content_type,
        storage_path=storage_path,
        file_size=file_size,
        sha256=digest,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)

    return MediaAssetRead.model_validate(asset).model_copy(update={"url": f"/storage/{asset.storage_path}"})
