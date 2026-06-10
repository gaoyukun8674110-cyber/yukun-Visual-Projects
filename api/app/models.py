from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


JSON_FIELD = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(32))
    content_type: Mapped[str | None] = mapped_column(String(128))
    storage_path: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    jobs: Mapped[list[DetectionJob]] = relationship(back_populates="media")


class DetectionJob(Base):
    __tablename__ = "detection_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(128), default="best.pt")
    result_path: Mapped[str | None] = mapped_column(String(512))
    result_json: Mapped[dict | None] = mapped_column(JSON_FIELD)
    error: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    media: Mapped[MediaAsset] = relationship(back_populates="jobs")
    logs: Mapped[list[JobLog]] = relationship(back_populates="job")


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("detection_jobs.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON_FIELD)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[DetectionJob] = relationship(back_populates="logs")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), index=True)
    weights_path: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
