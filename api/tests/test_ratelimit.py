from __future__ import annotations

from fastapi.testclient import TestClient

from helpers import PNG_BYTES, auth_headers, create_tables, fresh_api_modules, install_fake_redis


def test_create_job_rate_limit_is_counted_per_api_key(monkeypatch, tmp_path) -> None:
    modules = fresh_api_modules(
        monkeypatch,
        tmp_path,
        QUOTA_CONCURRENT_JOBS="100",
        QUOTA_JOBS_PER_DAY="100",
    )
    create_tables(modules)
    install_fake_redis(monkeypatch, modules)

    with TestClient(modules["main"].app) as client:
        media = client.post(
            "/api/media",
            files={"file": ("part.png", PNG_BYTES, "image/png")},
            headers=auth_headers(),
        )
        assert media.status_code == 201
        media_id = media.json()["id"]

        responses = [
            client.post(
                "/api/jobs",
                json={"media_id": media_id, "model_name": "best.pt"},
                headers=auth_headers(),
            )
            for _ in range(11)
        ]

    assert [response.status_code for response in responses[:10]] == [201] * 10
    assert responses[10].status_code == 429
    assert responses[10].headers["Retry-After"] == "60"
