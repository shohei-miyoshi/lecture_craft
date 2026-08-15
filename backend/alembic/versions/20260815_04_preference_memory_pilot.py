"""Add preference extraction fields to correction memories.

Revision ID: 20260815_04
Revises: 20260727_03
Create Date: 2026-08-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260815_04"
down_revision = "20260727_03"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    columns = _columns("correction_memories")
    if "preference_text" not in columns:
        op.add_column("correction_memories", sa.Column("preference_text", sa.Text(), nullable=True))
    if "preference_source" not in columns:
        op.add_column("correction_memories", sa.Column("preference_source", sa.Text(), nullable=True))
    if "preference_status" not in columns:
        op.add_column("correction_memories", sa.Column("preference_status", sa.Text(), nullable=True))
    if "preference_error" not in columns:
        op.add_column("correction_memories", sa.Column("preference_error", sa.Text(), nullable=True))
    if "preference_kind" not in columns:
        op.add_column("correction_memories", sa.Column("preference_kind", sa.Text(), nullable=True))
    if "preference_scope" not in columns:
        op.add_column("correction_memories", sa.Column("preference_scope", sa.Text(), nullable=True))
    if "preference_reason" not in columns:
        op.add_column("correction_memories", sa.Column("preference_reason", sa.Text(), nullable=True))
    if "context_text" not in columns:
        op.add_column("correction_memories", sa.Column("context_text", sa.Text(), nullable=True))
    if "context_embedding_json" not in columns:
        op.add_column("correction_memories", sa.Column("context_embedding_json", sa.Text(), nullable=False, server_default="[]"))
    if "edit_distance_ratio" not in columns:
        op.add_column("correction_memories", sa.Column("edit_distance_ratio", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("correction_memories", "edit_distance_ratio")
    op.drop_column("correction_memories", "preference_error")
    op.drop_column("correction_memories", "context_embedding_json")
    op.drop_column("correction_memories", "context_text")
    op.drop_column("correction_memories", "preference_reason")
    op.drop_column("correction_memories", "preference_scope")
    op.drop_column("correction_memories", "preference_kind")
    op.drop_column("correction_memories", "preference_status")
    op.drop_column("correction_memories", "preference_source")
    op.drop_column("correction_memories", "preference_text")
