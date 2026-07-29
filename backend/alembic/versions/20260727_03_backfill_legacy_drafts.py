"""Backfill editable drafts for projects created before Storage V2.

Revision ID: 20260727_03
Revises: 20260727_02
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op


revision = "20260727_03"
down_revision = "20260727_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO project_drafts (
            project_id, version, state_json, updated_by_user_id, created_at, updated_at
        )
        SELECT
            p.id,
            CASE
                WHEN COALESCE(
                    (SELECT MAX(pv.version_number) FROM project_versions AS pv WHERE pv.project_id = p.id),
                    1
                ) < 1 THEN 1
                ELSE COALESCE(
                    (SELECT MAX(pv.version_number) FROM project_versions AS pv WHERE pv.project_id = p.id),
                    1
                )
            END,
            COALESCE(NULLIF(p.latest_state_json, ''), '{}'),
            p.user_id,
            p.created_at,
            p.updated_at
        FROM projects AS p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_drafts AS d WHERE d.project_id = p.id
        )
        """
    )


def downgrade() -> None:
    # Backfilled drafts may have been edited after migration, so rollback must not delete them.
    pass
