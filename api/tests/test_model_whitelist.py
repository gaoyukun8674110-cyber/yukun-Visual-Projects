from __future__ import annotations

from fastapi.testclient import TestClient

from helpers import PNG_BYTES, auth_headers, create_tables, fresh_api_modules, install_fake_redis


def test_create_job_rejects_unsupported_model_name(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path)
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        media = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )
        assert media.status_code == 201

        response = client.post(
            "/api/jobs",
            json={"media_id": media.json()["id"], "model_name": "other.pt"},
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported model"


def test_create_job_rejects_model_path_injection(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path)
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        media = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )
        assert media.status_code == 201

        response = client.post(
            "/api/jobs",
            json={"media_id": media.json()["id"], "model_name": "../etc/passwd"},
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported model"
