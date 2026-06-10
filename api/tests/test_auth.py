from __future__ import annotations

from fastapi.testclient import TestClient

from helpers import PNG_BYTES, auth_headers, create_tables, fresh_api_modules, install_fake_redis


def test_health_is_public_but_jobs_require_api_key(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path)
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200

        missing_key = client.post("/api/jobs", json={"media_id": "missing", "model_name": "best.pt"})
        assert missing_key.status_code == 401
        assert missing_key.json()["detail"] == "Invalid API key"

        wrong_key = client.post(
            "/api/jobs",
            json={"media_id": "missing", "model_name": "best.pt"},
            headers=auth_headers("not-valid"),
        )
        assert wrong_key.status_code == 401
        assert wrong_key.json()["detail"] == "Invalid API key"


def test_valid_api_key_allows_authenticated_upload(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path)
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        response = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )

    assert response.status_code == 201
    assert response.json()["url"].startswith("/api/files/uploads/")
