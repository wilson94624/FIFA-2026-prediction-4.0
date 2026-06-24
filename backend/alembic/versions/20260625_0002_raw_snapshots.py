"""Add raw API and prediction snapshot archive.

Revision ID: 20260625_0002
Revises: 20260619_0001
Create Date: 2026-06-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260625_0002"
down_revision = "20260619_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("snapshot_type", sa.String(length=80), nullable=False),
        sa.Column("match_id", sa.String(length=40), nullable=True),
        sa.Column("external_match_id", sa.String(length=80), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prediction_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_raw_snapshots_source", "raw_snapshots", ["source"])
    op.create_index("ix_raw_snapshots_snapshot_type", "raw_snapshots", ["snapshot_type"])
    op.create_index("ix_raw_snapshots_match_id", "raw_snapshots", ["match_id"])
    op.create_index("ix_raw_snapshots_external_match_id", "raw_snapshots", ["external_match_id"])
    op.create_index("ix_raw_snapshots_fetched_at", "raw_snapshots", ["fetched_at"])
    op.create_index(
        "ix_raw_snapshots_prediction_timestamp",
        "raw_snapshots",
        ["prediction_timestamp"],
    )
    op.create_index("ix_raw_snapshots_payload_hash", "raw_snapshots", ["payload_hash"])
    op.create_index("ix_raw_snapshots_model_version", "raw_snapshots", ["model_version"])


def downgrade() -> None:
    op.drop_index("ix_raw_snapshots_model_version", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_payload_hash", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_prediction_timestamp", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_fetched_at", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_external_match_id", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_match_id", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_snapshot_type", table_name="raw_snapshots")
    op.drop_index("ix_raw_snapshots_source", table_name="raw_snapshots")
    op.drop_table("raw_snapshots")
