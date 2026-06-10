from __future__ import annotations

from fastapi.testclient import TestClient

from helpers import PNG_BYTES, auth_headers, create_tables, fresh_api_modules, install_fake_redis


def test_media_file_download_requires_api_key_and_matching_owner(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(monkeypatch, tmp_path)
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        upload = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )
        assert upload.status_code == 201
        file_url = upload.json()["url"]
        assert file_url.startswith("/api/files/uploads/")

        missing_key = client.get(file_url)
        other_owner = client.get(file_url, headers=auth_headers("otherkey"))
        owner = client.get(file_url, headers=auth_headers())
        traversal = client.get("/api/files/../.env", headers=auth_headers())

    assert missing_key.status_code == 401
    assert other_owner.status_code == 404
    assert owner.status_code == 200
    assert owner.content == PNG_BYTES
    assert traversal.status_code == 404
