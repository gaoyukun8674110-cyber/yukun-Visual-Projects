from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.config import get_settings
from app.db import add_job_log, complete_job, get_media, update_job_status
from app.inference import detect_media
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("worker")
settings = get_settings()


def _channel(job_id: str) -> str:
    return f"yolo:job:{job_id}:events"


async def publish(redis: Redis, job_id: str, event: str, payload: dict[str, Any]) -> None:
    await redis.publish(_channel(job_id), json.dumps({"event": event, "job_id": job_id, **payload}, ensure_ascii=False))


async def log_job(redis: Redis, job_id: str, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
    await add_job_log(job_id, level, message, payload)
    await publish(redis, job_id, "log", {"level": level, "message": message, "payload": payload})


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(settings.job_stream, settings.job_consumer_group, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def handle_job(redis: Redis, fields: dict[str, str]) -> None:
    job_id = fields["job_id"]
    media_id = fields["media_id"]
    model_name = fields.get("model_name", "best.pt")

    await update_job_status(job_id, "running", 10)
    await publish(redis, job_id, "status", {"status": "running", "progress": 10})
    await log_job(redis, job_id, "INFO", "worker 已接收任务", {"model_name": model_name})

    media = await get_media(media_id)
    if media is None:
        raise ValueError(f"Media asset not found: {media_id}")

    input_path = settings.storage_root / media["storage_path"]
    output_suffix = ".mp4" if media["media_type"] == "video" else ".jpg"
    result_rel = f"results/{job_id}{output_suffix}"
    output_path = settings.storage_root / result_rel

    await update_job_status(job_id, "running", 35)
    await publish(redis, job_id, "status", {"status": "running", "progress": 35})
    await log_job(redis, job_id, "INFO", "开始 YOLO 推理", {"input": str(input_path)})

    result = detect_media(Path(input_path), Path(output_path), settings)

    await complete_job(job_id, result_rel, result)
    await publish(
        redis,
        job_id,
        "completed",
        {"status": "succeeded", "progress": 100, "result_path": result_rel, "result_json": result},
    )
    await log_job(redis, job_id, "INFO", "任务完成", {"result_path": result_rel})


async def worker_loop() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await ensure_group(redis)
    logger.info("worker started")

    while True:
        messages = await redis.xreadgroup(
            groupname=settings.job_consumer_group,
            consumername=settings.worker_name,
            streams={settings.job_stream: ">"},
            count=1,
            block=5000,
        )
        if not messages:
            continue

        for _, entries in messages:
            for message_id, fields in entries:
                job_id = fields.get("job_id", "")
                try:
                    await handle_job(redis, fields)
                except Exception as exc:
                    logger.exception("job failed")
                    if job_id:
                        await update_job_status(job_id, "failed", 100, str(exc))
                        await log_job(redis, job_id, "ERROR", "任务失败", {"error": str(exc)})
                        await publish(redis, job_id, "failed", {"status": "failed", "progress": 100, "error": str(exc)})
                finally:
                    await redis.xack(settings.job_stream, settings.job_consumer_group, message_id)


if __name__ == "__main__":
    asyncio.run(worker_loop())
