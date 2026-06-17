from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL_FILENAME = "best.pt"


def _candidate_model_paths(anchor_file: Path | None = None) -> list[Path]:
    anchor = (anchor_file or Path(__file__)).resolve()
    return [
        anchor.parents[1] / "models" / DEFAULT_MODEL_FILENAME,
        anchor.parents[2] / "models" / DEFAULT_MODEL_FILENAME,
    ]


def resolve_default_model_path(anchor_file: Path | None = None) -> Path:
    candidates = _candidate_model_paths(anchor_file)
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    for candidate in candidates:
        if candidate.parent.exists():
            return candidate

    return candidates[0]


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://yolo:yolo_dev_password@localhost:5432/yolo"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("../storage")
    job_stream: str = "yolo:jobs"
    job_consumer_group: str = "yolo-workers"
    worker_name: str = "worker-1"
    yolo_confidence: float = 0.35
    yolo_device: str = "auto"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def yolo_model_path(self) -> Path:
        return resolve_default_model_path()


@lru_cache
def get_settings() -> Settings:
    return Settings()
