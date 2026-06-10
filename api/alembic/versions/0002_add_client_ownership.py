"""add client ownership columns

Revision ID: 0002_add_client_ownership
Revises: 0001_initial
Create Date: 2026-06-10 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_add_client_ownership"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.create_index("ix_media_assets_client_id", "media_assets", ["client_id"])
    op.add_column("detection_jobs", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.create_index("ix_detection_jobs_client_id", "detection_jobs", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_detection_jobs_client_id", table_name="detection_jobs")
    op.drop_column("detection_jobs", "client_id")
    op.drop_index("ix_media_assets_client_id", table_name="media_assets")
    op.drop_column("media_assets", "client_id")
