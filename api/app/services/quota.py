from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from math import ceil

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import DetectionJob


@dataclass
class QuotaExceeded(Exception):
    status_code: int
    detail: str
    limit: int
    used: int
    reset_at: datetime | None = None

    @property
    def quota(self) -> dict[str, int | str | None]:
        return {
            "limit": self.limit,
            "used": self.used,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
        }


async def quota_exceeded_handler(request: Request, exc: QuotaExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "quota": exc.quota},
    )


def _utc_midnight_after(now: datetime) -> datetime:
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=UTC)


def _bytes_to_mb_ceil(value: int) -> int:
    if value <= 0:
        return 0
    return ceil(value / (1024 * 1024))


async def consume_daily_job_quota(redis: Redis, client_id: str) -> None:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    reset_at = _utc_midnight_after(now)
    key = f"quota:jobs:{client_id}:{now:%Y%m%d}"

    used = int(await redis.incr(key))
    if used == 1:
        await redis.expire(key, max(1, int((reset_at - now).total_seconds())))

    if used > settings.quota_jobs_per_day:
        await redis.decr(key)
        raise QuotaExceeded(
            status_code=429,
            detail="Daily job quota exceeded",
            limit=settings.quota_jobs_per_day,
            used=settings.quota_jobs_per_day,
            reset_at=reset_at,
        )


async def rollback_daily_job_quota(redis: Redis, client_id: str) -> None:
    now = datetime.now(tz=UTC)
    key = f"quota:jobs:{client_id}:{now:%Y%m%d}"
    await redis.decr(key)


async def add_storage_usage(redis: Redis, client_id: str, file_size: int) -> None:
    settings = get_settings()
    key = f"quota:storage:{client_id}"
    limit_bytes = settings.quota_storage_mb * 1024 * 1024

    used_bytes = int(await redis.incrby(key, file_size))
    if used_bytes > limit_bytes:
        await redis.decrby(key, file_size)
        raise QuotaExceeded(
            status_code=413,
            detail="Storage quota exceeded",
            limit=settings.quota_storage_mb,
            used=_bytes_to_mb_ceil(used_bytes),
            reset_at=None,
        )


async def rollback_storage_usage(redis: Redis, client_id: str, file_size: int) -> None:
    await redis.decrby(f"quota:storage:{client_id}", file_size)


async def ensure_active_job_quota(session: AsyncSession, client_id: str) -> None:
    settings = get_settings()
    result = await session.execute(
        select(func.count(DetectionJob.id)).where(
            DetectionJob.client_id == client_id,
            DetectionJob.status.in_(("queued", "running")),
        )
    )
    used = int(result.scalar_one())
    if used >= settings.quota_concurrent_jobs:
        raise QuotaExceeded(
            status_code=429,
            detail="Too many active jobs",
            limit=settings.quota_concurrent_jobs,
            used=used,
            reset_at=None,
        )
