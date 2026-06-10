from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "YOLO Detection Framework"
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://yolo:yolo_dev_password@localhost:5432/yolo"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("../storage")
    job_stream: str = "yolo:jobs"
    job_consumer_group: str = "yolo-workers"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    max_upload_mb: int = 512
    auth_enabled: bool = True
    api_keys: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["devkey1"])
    allowed_models: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["best.pt"])
    quota_jobs_per_day: int = 200
    quota_storage_mb: int = 10240
    quota_concurrent_jobs: int = 3
    queue_max_depth: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def uploads_dir(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.storage_root / "results"

    @field_validator("api_keys", "allowed_models", "cors_origins", mode="before")
    @classmethod
    def parse_string_list(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("Expected a list")
            return parsed
        return [part.strip() for part in text.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
