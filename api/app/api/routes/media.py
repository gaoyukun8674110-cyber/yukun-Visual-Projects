from fastapi import APIRouter, Depends, Request, UploadFile
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.core.security import require_api_key
from app.db import get_session
from app.models import MediaAsset
from app.schemas import MediaAssetRead
from app.services.queue import get_redis
from app.services.quota import QuotaExceeded, add_storage_usage, rollback_storage_usage
from app.services.storage import save_upload

router = APIRouter()
settings = get_settings()


def _remove_stored_file(storage_path: str | None) -> None:
    if not storage_path:
        return
    (settings.storage_root / storage_path).unlink(missing_ok=True)


@router.post("", response_model=MediaAssetRead, status_code=201)
@limiter.limit("20/minute")
async def upload_media(
    request: Request,
    file: UploadFile,
    client_id: str = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> MediaAssetRead:
    redis: Redis = await get_redis()
    storage_path: str | None = None
    file_size = 0
    storage_counted = False

    try:
        storage_path, kind, file_size, digest = await save_upload(file)
        await add_storage_usage(redis, client_id, file_size)
        storage_counted = True

        asset = MediaAsset(
            original_filename=file.filename or "upload",
            media_type=kind,
            content_type=file.content_type,
            storage_path=storage_path,
            file_size=file_size,
            sha256=digest,
            client_id=client_id,
        )
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
    except QuotaExceeded:
        _remove_stored_file(storage_path)
        raise
    except Exception:
        if storage_counted:
            await rollback_storage_usage(redis, client_id, file_size)
        _remove_stored_file(storage_path)
        await session.rollback()
        raise
    finally:
        await redis.aclose()

    return MediaAssetRead.model_validate(asset).model_copy(update={"url": f"/api/files/{asset.storage_path}"})
