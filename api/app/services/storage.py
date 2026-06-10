from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

settings = get_settings()

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska", "video/webm"}
CHUNK_SIZE = 1024 * 1024


def ensure_storage_dirs() -> None:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.results_dir.mkdir(parents=True, exist_ok=True)


def media_kind(content_type: str | None) -> str:
    normalized = normalize_content_type(content_type)
    if normalized in IMAGE_TYPES:
        return "image"
    if normalized in VIDEO_TYPES:
        return "video"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Unsupported media type: {content_type}",
    )


def normalize_content_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def magic_matches(content_type: str | None, chunk: bytes) -> bool:
    normalized = normalize_content_type(content_type)
    if normalized == "image/jpeg":
        return chunk.startswith(b"\xff\xd8\xff")
    if normalized == "image/png":
        return chunk.startswith(b"\x89PNG")
    if normalized == "image/webp":
        return len(chunk) >= 12 and chunk.startswith(b"RIFF") and chunk[8:12] == b"WEBP"
    if normalized == "image/bmp":
        return chunk.startswith(b"BM")
    if normalized in {"video/mp4", "video/quicktime"}:
        return len(chunk) >= 8 and chunk[4:8] == b"ftyp"
    if normalized in {"video/x-matroska", "video/webm"}:
        return chunk.startswith(b"\x1a\x45\xdf\xa3")
    if normalized == "video/x-msvideo":
        return len(chunk) >= 12 and chunk.startswith(b"RIFF") and chunk[8:12] == b"AVI "
    return False


async def save_upload(file: UploadFile) -> tuple[str, str, int, str]:
    ensure_storage_dirs()
    kind = media_kind(file.content_type)
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    filename = f"{uuid4().hex}{suffix}"
    target = settings.uploads_dir / filename

    digest = hashlib.sha256()
    total = 0
    limit = settings.max_upload_mb * 1024 * 1024

    try:
        with target.open("wb") as out:
            first_chunk = await file.read(CHUNK_SIZE)
            if not first_chunk or not magic_matches(file.content_type, first_chunk):
                raise HTTPException(status_code=415, detail="File content does not match declared type")

            total += len(first_chunk)
            if total > limit:
                raise HTTPException(status_code=413, detail="Uploaded file is too large")
            digest.update(first_chunk)
            out.write(first_chunk)

            while chunk := await file.read(CHUNK_SIZE):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(status_code=413, detail="Uploaded file is too large")
                digest.update(chunk)
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise

    return f"uploads/{filename}", kind, total, digest.hexdigest()
