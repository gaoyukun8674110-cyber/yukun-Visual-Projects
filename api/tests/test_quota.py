from __future__ import annotations

from fastapi.testclient import TestClient

from helpers import (
    PNG_BYTES,
    FakeRedis,
    auth_headers,
    client_id_for_key,
    create_tables,
    fresh_api_modules,
    install_fake_redis,
    run,
)


def _upload_media(client: TestClient) -> str:
    response = client.post(
        "/api/media",
        files={"file": ("part.png", PNG_BYTES, "image/png")},
        headers=auth_headers(),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_daily_job_quota_returns_429_after_limit(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(
        monkeypatch,
        tmp_path,
        QUOTA_JOBS_PER_DAY="1",
        QUOTA_CONCURRENT_JOBS="100",
    )
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        media_id = _upload_media(client)

        first = client.post(
            "/api/jobs",
            json={"media_id": media_id, "model_name": "best.pt"},
            headers=auth_headers(),
        )
        assert first.status_code == 201

        second = client.post(
            "/api/jobs",
            json={"media_id": media_id, "model_name": "best.pt"},
            headers=auth_headers(),
        )

    assert second.status_code == 429
    assert second.json()["detail"] == "Daily job quota exceeded"
    assert second.json()["quota"]["limit"] == 1


def test_concurrent_job_quota_counts_active_jobs_by_client_id(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path, QUOTA_CONCURRENT_JOBS="1")
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)
    models = modules["models"]
    db = modules["db"]

    with TestClient(modules["main"].app) as client:
        media_id = _upload_media(client)

    async def add_active_job() -> None:
        async with db.async_session.begin() as session:
            session.add(
                models.DetectionJob(
                    media_id=media_id,
                    status="running",
                    progress=50,
                    model_name="best.pt",
                    client_id=client_id_for_key("devkey1"),
                )
            )

    run(add_active_job())

    with TestClient(modules["main"].app) as client:
        response = client.post(
            "/api/jobs",
            json={"media_id": media_id, "model_name": "best.pt"},
            headers=auth_headers(),
        )

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many active jobs"
    assert response.json()["quota"]["limit"] == 1


def test_storage_quota_removes_file_and_returns_413(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path, QUOTA_STORAGE_MB="0")
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        response = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Storage quota exceeded"
    assert response.json()["quota"]["limit"] == 0
    assert not list((tmp_path / "storage" / "uploads").glob("*"))


def test_queue_backpressure_returns_503_with_retry_after(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path, QUEUE_MAX_DEPTH="500", QUOTA_CONCURRENT_JOBS="100")
    create_tables(modules)
    fake_redis = install_fake_redis(monkeypatch, modules, FakeRedis(queue_depth=501))

    with TestClient(modules["main"].app) as client:
        media_id = _upload_media(client)
        response = client.post(
            "/api/jobs",
            json={"media_id": media_id, "model_name": "best.pt"},
            headers=auth_headers(),
        )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.json()["detail"] == "System busy, retry later"
    assert all(event["type"] != "xadd" for event in fake_redis.events)
