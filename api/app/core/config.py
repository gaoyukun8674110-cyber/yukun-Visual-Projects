from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "YOLO Detection Framework"
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://yolo:yolo_dev_password@localhost:5432/yolo"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("../storage")
    job_stream: str = "yolo:jobs"
    job_consumer_group: str = "yolo-workers"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    max_upload_mb: int = 512

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
