from __future__ import annotations

from fastapi.testclient import TestClient

from helpers import PNG_BYTES, auth_headers, create_tables, fresh_api_modules, install_fake_redis


def test_upload_rejects_declared_image_when_magic_bytes_do_not_match(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path)
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        response = client.post(
            "/api/media",
            files={"file": ("renamed.jpg", b"MZ fake executable", "image/jpeg")},
            headers=auth_headers(),
        )

    assert response.status_code == 415
    assert response.json()["detail"] == "File content does not match declared type"
    assert not list((tmp_path / "storage" / "uploads").glob("*"))


def test_upload_rejects_files_larger_than_configured_limit(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path, MAX_UPLOAD_MB="0")
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        response = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded file is too large"
    assert not list((tmp_path / "storage" / "uploads").glob("*"))
