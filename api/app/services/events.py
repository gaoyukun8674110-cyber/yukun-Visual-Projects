from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis


def job_channel(job_id: str) -> str:
    return f"yolo:job:{job_id}:events"


async def publish_job_event(redis: Redis, job_id: str, event: str, payload: dict[str, Any]) -> None:
    message = {"event": event, "job_id": job_id, **payload}
    await redis.publish(job_channel(job_id), json.dumps(message, ensure_ascii=False))
