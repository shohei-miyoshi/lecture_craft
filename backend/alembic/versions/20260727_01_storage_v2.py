"""Add the run-centric storage catalog.

Revision ID: 20260727_01
Revises:
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260727_01"
down_revision = None
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def _add_column(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    if not _table_exists("projects"):
        if _table_exists("users"):
            raise RuntimeError("Partial LectureCraft schema detected; restore a consistent DB before migration")
        # Fresh installations still enter through Alembic. The shared bootstrap creates
        # the complete baseline on the configured database; app startup never calls it
        # in production.
        from app.db import init_db

        init_db()
        return

    _add_column("projects", sa.Column("usage_context", sa.Text(), nullable=False, server_default="general"))
    _add_column("projects", sa.Column("analysis_status", sa.Text(), nullable=False, server_default="candidate"))
    _add_column("projects", sa.Column("current_source_artifact_id", sa.Text(), nullable=True))
    _add_column("projects", sa.Column("active_run_id", sa.Text(), nullable=True))
    _add_column("projects", sa.Column("archived_at", sa.Text(), nullable=True))
    _add_column("generation_runs", sa.Column("source_artifact_id", sa.Text(), nullable=True))
    _add_column("generation_runs", sa.Column("usage_context", sa.Text(), nullable=False, server_default="general"))
    _add_column("generation_runs", sa.Column("analysis_status", sa.Text(), nullable=False, server_default="candidate"))
    _add_column("generation_runs", sa.Column("reused_from_run_id", sa.Text(), nullable=True))
    _add_column("generation_runs", sa.Column("model_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column("generation_runs", sa.Column("prompt_json", sa.Text(), nullable=False, server_default="{}"))

    op.create_table(
        "project_drafts",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_by_user_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "project_revisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("generation_run_id", sa.Text()),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_kind", sa.Text(), nullable=False),
        sa.Column("parent_revision_id", sa.Text()),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["project_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "revision_number"),
    )
    op.create_index("idx_project_revisions_project", "project_revisions", ["project_id", "revision_number"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_user_id", sa.Text()),
        sa.Column("owner_session_id", sa.Text()),
        sa.Column("project_id", sa.Text()),
        sa.Column("generation_run_id", sa.Text()),
        sa.Column("request_key", sa.Text()),
        sa.Column("request_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_artifact_id", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("partial_result_json", sa.Text()),
        sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_expires_at", sa.Text()),
        sa.Column("heartbeat_at", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_jobs_queue", "jobs", ["status", "created_at"])
    op.create_index("idx_jobs_run", "jobs", ["generation_run_id", "created_at"])
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("generation_run_id", sa.Text()),
        sa.Column("project_revision_id", sa.Text()),
        sa.Column("job_id", sa.Text()),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("storage_backend", sa.Text(), nullable=False, server_default="local"),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.Text()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_revision_id"], ["project_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_artifacts_project", "artifacts", ["project_id", "created_at"])
    op.create_index("idx_artifacts_run", "artifacts", ["generation_run_id", "stage", "created_at"])
    op.create_index("idx_artifacts_hash", "artifacts", ["sha256"])
    op.create_table(
        "artifact_relations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_artifact_id", sa.Text(), nullable=False),
        sa.Column("target_artifact_id", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_artifact_id", "target_artifact_id", "relation_type"),
    )
    op.create_table(
        "review_stage_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("generation_run_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_revision_id", sa.Text()),
        sa.Column("output_revision_id", sa.Text(), nullable=False),
        sa.Column("invalidated_reason", sa.Text()),
        sa.Column("confirmed_by_user_id", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["input_revision_id"], ["project_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_revision_id"], ["project_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("generation_run_id", "stage", "version_number"),
    )
    op.create_index(
        "idx_review_stage_versions_active",
        "review_stage_versions",
        ["generation_run_id", "stage", "status"],
    )
    op.create_table(
        "cache_entries",
        sa.Column("cache_key", sa.Text(), primary_key=True),
        sa.Column("cache_kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_accessed_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cache_entries")
    op.drop_index("idx_review_stage_versions_active", table_name="review_stage_versions")
    op.drop_table("review_stage_versions")
    op.drop_table("artifact_relations")
    op.drop_index("idx_artifacts_hash", table_name="artifacts")
    op.drop_index("idx_artifacts_run", table_name="artifacts")
    op.drop_index("idx_artifacts_project", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("idx_jobs_run", table_name="jobs")
    op.drop_index("idx_jobs_queue", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("idx_project_revisions_project", table_name="project_revisions")
    op.drop_table("project_revisions")
    op.drop_table("project_drafts")
