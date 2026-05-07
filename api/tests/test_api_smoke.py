from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select


def _fresh_api_modules(monkeypatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'smoke.db'}")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6390/0")

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    modules = {
        "main": importlib.import_module("app.main"),
        "db": importlib.import_module("app.db"),
        "models": importlib.import_module("app.models"),
        "jobs": importlib.import_module("app.api.routes.jobs"),
    }
    return modules


def _run(coro):
    return asyncio.run(coro)


def test_media_upload_and_job_create_smoke(monkeypatch, tmp_path: Path) -> None:
    modules = _fresh_api_modules(monkeypatch, tmp_path)
    db = modules["db"]
    models = modules["models"]
    jobs = modules["jobs"]
    app = modules["main"].app

    async def create_tables() -> None:
        async with db.engine.begin() as connection:
            await connection.run_sync(models.Base.metadata.create_all)

    _run(create_tables())

    queue_events: list[dict[str, Any]] = []

    class FakeRedis:
        async def aclose(self) -> None:
            return None

    async def fake_get_redis() -> FakeRedis:
        return FakeRedis()

    async def fake_enqueue_detection_job(redis: FakeRedis, job_id: str, media_id: str, model_name: str) -> str:
        queue_events.append({"type": "enqueue", "job_id": job_id, "media_id": media_id, "model_name": model_name})
        return "queued-1"

    async def fake_publish_job_event(redis: FakeRedis, job_id: str, event: str, payload: dict[str, Any]) -> None:
        queue_events.append({"type": "publish", "job_id": job_id, "event": event, "payload": payload})

    monkeypatch.setattr(jobs, "get_redis", fake_get_redis)
    monkeypatch.setattr(jobs, "enqueue_detection_job", fake_enqueue_detection_job)
    monkeypatch.setattr(jobs, "publish_job_event", fake_publish_job_event)

    with TestClient(app) as client:
        media_response = client.post(
            "/api/media",
            files={"file": ("part.png", b"fake image bytes", "image/png")},
        )
        assert media_response.status_code == 201
        media_payload = media_response.json()

        assert media_payload["original_filename"] == "part.png"
        assert media_payload["media_type"] == "image"
        assert media_payload["content_type"] == "image/png"
        assert media_payload["file_size"] == len(b"fake image bytes")
        assert media_payload["storage_path"].startswith("uploads/")
        assert media_payload["url"] == f"/storage/{media_payload['storage_path']}"
        assert (tmp_path / "storage" / media_payload["storage_path"]).is_file()

        job_response = client.post(
            "/api/jobs",
            json={"media_id": media_payload["id"], "model_name": "best.pt"},
        )
        assert job_response.status_code == 201
        job_payload = job_response.json()

        assert job_payload["media_id"] == media_payload["id"]
        assert job_payload["status"] == "queued"
        assert job_payload["progress"] == 0
        assert job_payload["model_name"] == "best.pt"
        assert job_payload["result_path"] is None
        assert job_payload["result_url"] is None

    async def read_records() -> tuple[Any, Any, list[Any]]:
        async with db.async_session() as session:
            media = await session.get(models.MediaAsset, media_payload["id"])
            job = await session.get(models.DetectionJob, job_payload["id"])
            logs = (
                await session.execute(
                    select(models.JobLog).where(models.JobLog.job_id == job_payload["id"])
                )
            ).scalars().all()
            return media, job, logs

    media_record, job_record, log_records = _run(read_records())

    assert media_record is not None
    assert media_record.storage_path == media_payload["storage_path"]
    assert media_record.file_size == len(b"fake image bytes")
    assert job_record is not None
    assert job_record.status == "queued"
    assert job_record.media_id == media_payload["id"]
    assert len(log_records) == 1
    assert "等待 worker 消费" in log_records[0].message
    assert queue_events == [
        {"type": "enqueue", "job_id": job_payload["id"], "media_id": media_payload["id"], "model_name": "best.pt"},
        {"type": "publish", "job_id": job_payload["id"], "event": "queued", "payload": {"status": "queued", "progress": 0}},
    ]
