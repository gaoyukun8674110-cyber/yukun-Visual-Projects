from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings


def client_id_for_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    settings = get_settings()
    if not settings.auth_enabled:
        client_id = "anonymous"
        request.state.client_id = client_id
        return client_id

    if not x_api_key or x_api_key not in set(settings.api_keys):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    client_id = client_id_for_api_key(x_api_key)
    request.state.client_id = client_id
    return client_id
