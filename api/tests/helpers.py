from __future__ import annotations

import asyncio
import hashlib
import importlib
import sys
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class FakeRedis:
    def __init__(self, queue_depth: int = 0) -> None:
        self.queue_depth = queue_depth
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}
        self.events: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        return None

    async def xadd(self, stream: str, fields: dict[str, Any]) -> str:
        self.events.append({"type": "xadd", "stream": stream, "fields": fields})
        return "queued-1"

    async def xlen(self, stream: str) -> int:
        return self.queue_depth

    async def publish(self, channel: str, payload: str) -> int:
        self.events.append({"type": "publish", "channel": channel, "payload": payload})
        return 1

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def incrby(self, key: str, amount: int) -> int:
        self.values[key] = self.values.get(key, 0) + amount
        return self.values[key]

    async def decrby(self, key: str, amount: int) -> int:
        self.values[key] = self.values.get(key, 0) - amount
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def client_id_for_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def fresh_api_modules(monkeypatch: Any, tmp_path: Path, **env: str) -> dict[str, Any]:
    defaults = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "STORAGE_ROOT": str(tmp_path / "storage"),
        "REDIS_URL": "memory://",
        "AUTH_ENABLED": "true",
        "API_KEYS": "devkey1,otherkey",
        "ALLOWED_MODELS": "best.pt",
        "CORS_ORIGINS": '["http://localhost:3000"]',
        "MAX_UPLOAD_MB": "512",
        "QUOTA_JOBS_PER_DAY": "200",
        "QUOTA_STORAGE_MB": "10240",
        "QUOTA_CONCURRENT_JOBS": "3",
        "QUEUE_MAX_DEPTH": "500",
    }
    defaults.update(env)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    return {
        "main": importlib.import_module("app.main"),
        "db": importlib.import_module("app.db"),
        "models": importlib.import_module("app.models"),
        "jobs": importlib.import_module("app.api.routes.jobs"),
        "media": importlib.import_module("app.api.routes.media"),
    }


def create_tables(modules: dict[str, Any]) -> None:
    db = modules["db"]
    models = modules["models"]

    async def _create() -> None:
        async with db.engine.begin() as connection:
            await connection.run_sync(models.Base.metadata.create_all)

    run(_create())


def install_fake_redis(monkeypatch: Any, modules: dict[str, Any], fake_redis: FakeRedis | None = None) -> FakeRedis:
    fake_redis = fake_redis or FakeRedis()

    async def fake_get_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr(modules["jobs"], "get_redis", fake_get_redis)
    monkeypatch.setattr(modules["media"], "get_redis", fake_get_redis, raising=False)
    return fake_redis


def auth_headers(api_key: str = "devkey1") -> dict[str, str]:
    return {"X-API-Key": api_key}
