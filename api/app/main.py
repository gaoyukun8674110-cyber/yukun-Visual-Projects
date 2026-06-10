from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.ratelimit import limiter, rate_limit_exceeded_handler
from app.services.quota import QuotaExceeded, quota_exceeded_handler
from app.services.storage import ensure_storage_dirs

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_exception_handler(QuotaExceeded, quota_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)
app.add_middleware(SlowAPIMiddleware)


@app.on_event("startup")
async def on_startup() -> None:
    ensure_storage_dirs()


ensure_storage_dirs()
app.include_router(router, prefix=settings.api_prefix)
