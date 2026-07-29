"""Associate edit memories with generation runs.

Revision ID: 20260727_02
Revises: 20260727_01
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260727_02"
down_revision = "20260727_01"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {str(index["name"]) for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "generation_run_id" not in _columns("edit_events"):
        op.add_column("edit_events", sa.Column("generation_run_id", sa.Text(), nullable=True))
    if "generation_run_id" not in _columns("correction_memories"):
        op.add_column("correction_memories", sa.Column("generation_run_id", sa.Text(), nullable=True))
    if "idx_edit_events_generation_run" not in _indexes("edit_events"):
        op.create_index(
            "idx_edit_events_generation_run",
            "edit_events",
            ["generation_run_id", "created_at"],
        )
    if "idx_correction_memories_generation_run" not in _indexes("correction_memories"):
        op.create_index(
            "idx_correction_memories_generation_run",
            "correction_memories",
            ["generation_run_id", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("idx_correction_memories_generation_run", table_name="correction_memories")
    op.drop_index("idx_edit_events_generation_run", table_name="edit_events")
    op.drop_column("correction_memories", "generation_run_id")
    op.drop_column("edit_events", "generation_run_id")
