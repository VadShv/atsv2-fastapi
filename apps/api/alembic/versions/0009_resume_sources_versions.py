"""Resume sources and versions tables.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = ["resume_sources", "resume_versions"]


def upgrade() -> None:
    # 1. resume_sources — каналы привлечения резюме
    op.create_table(
        "resume_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("external_id", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resume_sources_tenant_id", "resume_sources", ["tenant_id"])
    op.create_index("ix_resume_sources_candidate_id", "resume_sources", ["candidate_id"])

    # 2. resume_versions — версии резюме с content-hash и parsed_data
    op.create_table(
        "resume_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resume_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_storage_key", sa.String(1000), nullable=False, server_default=""),
        sa.Column("original_filename", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("parser_version", sa.String(50), nullable=False, server_default=""),
        sa.Column(
            "provenance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provenance.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("parsed_data", postgresql.JSONB, nullable=True),
        sa.Column("parse_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resume_versions_tenant_id", "resume_versions", ["tenant_id"])
    op.create_index("ix_resume_versions_candidate_id", "resume_versions", ["candidate_id"])
    op.create_index("ix_resume_versions_content_hash", "resume_versions", ["content_hash"])
    # Уникальный индекс: один content_hash на кандидата (дедупликация)
    op.create_index(
        "ux_resume_versions_candidate_hash",
        "resume_versions",
        ["tenant_id", "candidate_id", "content_hash"],
        unique=True,
    )

    _apply_rls()


def _apply_rls() -> None:
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )
        op.execute(
            f"CREATE POLICY tenant_isolation_write ON {table} "
            f"WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_write ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ux_resume_versions_candidate_hash", table_name="resume_versions")
    op.drop_index("ix_resume_versions_content_hash", table_name="resume_versions")
    op.drop_index("ix_resume_versions_candidate_id", table_name="resume_versions")
    op.drop_index("ix_resume_versions_tenant_id", table_name="resume_versions")
    op.drop_table("resume_versions")

    op.drop_index("ix_resume_sources_candidate_id", table_name="resume_sources")
    op.drop_index("ix_resume_sources_tenant_id", table_name="resume_sources")
    op.drop_table("resume_sources")
