from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.security import client_id_for_api_key


def rate_limit_key(request: Request) -> str:
    client_id = getattr(request.state, "client_id", None)
    if client_id:
        return str(client_id)

    api_key = request.headers.get("x-api-key")
    if api_key:
        return client_id_for_api_key(api_key)

    return get_remote_address(request)


settings = get_settings()
limiter = Limiter(key_func=rate_limit_key, storage_uri=settings.redis_url)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    response = JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    response.headers["Retry-After"] = "60"
    return response
