"""Initial schema — thread_mappings and activity_log tables

Revision ID: 001
Revises:
Create Date: 2026-02-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "thread_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Integer, nullable=False, unique=True),
        sa.Column("slack_thread_ts", sa.String(64), nullable=False),
        sa.Column("slack_channel_id", sa.String(32), nullable=False),
        sa.Column("inbox_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_thread_mappings_conversation_id", "thread_mappings", ["conversation_id"])

    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbox_id", sa.Integer, nullable=True),
        sa.Column("inbox_name", sa.String(128), nullable=False, server_default="—"),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
    )
    op.create_index("ix_activity_log_ts", "activity_log", ["ts"])


def downgrade() -> None:
    op.drop_table("activity_log")
    op.drop_table("thread_mappings")
