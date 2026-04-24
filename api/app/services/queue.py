from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()


async def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def enqueue_detection_job(redis: Redis, job_id: str, media_id: str, model_name: str) -> str:
    return await redis.xadd(
        settings.job_stream,
        {
            "job_id": job_id,
            "media_id": media_id,
            "model_name": model_name,
        },
    )
