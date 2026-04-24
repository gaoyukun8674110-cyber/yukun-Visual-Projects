from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.storage import ensure_storage_dirs

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    ensure_storage_dirs()


ensure_storage_dirs()
app.include_router(router, prefix=settings.api_prefix)
app.mount("/storage", StaticFiles(directory=settings.storage_root), name="storage")
