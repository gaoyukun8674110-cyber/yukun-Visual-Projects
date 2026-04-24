from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaAssetRead(BaseModel):
    id: str
    original_filename: str
    media_type: str
    content_type: str | None
    storage_path: str
    file_size: int
    sha256: str
    created_at: datetime
    url: str = ""

    model_config = ConfigDict(from_attributes=True)


class JobCreate(BaseModel):
    media_id: str
    model_name: str = "best.pt"


class DetectionJobRead(BaseModel):
    id: str
    media_id: str
    status: str
    progress: int
    model_name: str
    result_path: str | None
    result_json: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    result_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JobLogRead(BaseModel):
    id: str
    job_id: str
    level: str
    message: str
    payload: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HealthRead(BaseModel):
    ok: bool
    service: str
