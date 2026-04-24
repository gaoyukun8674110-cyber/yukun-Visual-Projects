"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-11 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_media_assets_created_at", "media_assets", ["created_at"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("weights_path", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_versions_name", "model_versions", ["name"])

    op.create_table(
        "detection_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("media_id", sa.String(length=36), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default="best.pt"),
        sa.Column("result_path", sa.String(length=512), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_detection_jobs_created_at", "detection_jobs", ["created_at"])
    op.create_index("ix_detection_jobs_status", "detection_jobs", ["status"])

    op.create_table(
        "job_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("detection_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="INFO"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_logs_job_id_created_at", "job_logs", ["job_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_logs_job_id_created_at", table_name="job_logs")
    op.drop_table("job_logs")
    op.drop_index("ix_detection_jobs_status", table_name="detection_jobs")
    op.drop_index("ix_detection_jobs_created_at", table_name="detection_jobs")
    op.drop_table("detection_jobs")
    op.drop_index("ix_model_versions_name", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_index("ix_media_assets_created_at", table_name="media_assets")
    op.drop_table("media_assets")
