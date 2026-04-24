from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

settings = get_settings()

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska"}


def ensure_storage_dirs() -> None:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.results_dir.mkdir(parents=True, exist_ok=True)


def media_kind(content_type: str | None) -> str:
    if content_type in IMAGE_TYPES:
        return "image"
    if content_type in VIDEO_TYPES:
        return "video"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Unsupported media type: {content_type}",
    )


async def save_upload(file: UploadFile) -> tuple[str, str, int, str]:
    ensure_storage_dirs()
    kind = media_kind(file.content_type)
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    filename = f"{uuid4().hex}{suffix}"
    target = settings.uploads_dir / filename

    digest = hashlib.sha256()
    total = 0
    limit = settings.max_upload_mb * 1024 * 1024

    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Uploaded file is too large")
            digest.update(chunk)
            out.write(chunk)

    return f"uploads/{filename}", kind, total, digest.hexdigest()
