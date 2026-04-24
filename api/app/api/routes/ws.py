from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.events import job_channel
from app.services.queue import get_redis

router = APIRouter()


@router.websocket("/jobs/{job_id}")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(job_channel(job_id))

    try:
        await websocket.send_json({"event": "connected", "job_id": job_id})
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
    finally:
        await pubsub.unsubscribe(job_channel(job_id))
        await pubsub.aclose()
        await redis.aclose()
