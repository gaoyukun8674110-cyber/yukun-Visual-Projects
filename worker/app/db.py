from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_media(media_id: str) -> dict[str, Any] | None:
    async with Session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, original_filename, media_type, storage_path, content_type
                FROM media_assets
                WHERE id = :media_id
                """
            ),
            {"media_id": media_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


async def update_job_status(job_id: str, status: str, progress: int, error: str | None = None) -> None:
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                UPDATE detection_jobs
                SET status = :status, progress = :progress, error = :error, updated_at = now()
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "status": status, "progress": progress, "error": error},
        )


async def complete_job(job_id: str, result_path: str, result_json: dict[str, Any]) -> None:
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                UPDATE detection_jobs
                SET status = 'succeeded',
                    progress = 100,
                    result_path = :result_path,
                    result_json = CAST(:result_json AS JSONB),
                    error = NULL,
                    updated_at = now()
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "result_path": result_path, "result_json": json.dumps(result_json)},
        )


async def add_job_log(job_id: str, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
    async with Session.begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO job_logs (id, job_id, level, message, payload, created_at)
                VALUES (:id, :job_id, :level, :message, CAST(:payload AS JSONB), now())
                """
            ),
            {
                "id": str(uuid4()),
                "job_id": job_id,
                "level": level,
                "message": message,
                "payload": json.dumps(payload) if payload is not None else None,
            },
        )
