"""Candidates + applications tables (CRM 360 + pipeline).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = ["candidates", "applications"]


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(500), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("pii_token", sa.String(255), nullable=True),
        sa.Column("headline", sa.String(500), nullable=False, server_default=""),
        sa.Column("skills", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "resume_provenance",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provenance.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_candidates_tenant_id", "candidates", ["tenant_id"])
    op.create_index("ix_candidates_resume_provenance", "candidates", ["resume_provenance"])

    op.create_table(
        "applications",
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
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(50), nullable=False, server_default="new"),
        sa.Column("transitions", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column(
            "score_provenance",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provenance.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_applications_tenant_id", "applications", ["tenant_id"])
    op.create_index("ix_applications_candidate_id", "applications", ["candidate_id"])
    op.create_index("ix_applications_vacancy_id", "applications", ["vacancy_id"])
    op.create_index(
        "ix_applications_candidate_vacancy",
        "applications",
        ["tenant_id", "candidate_id", "vacancy_id"],
        unique=True,
    )

    _apply_rls()


def _apply_rls() -> None:
    for table in TENANT_TABLES:
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
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_write ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_applications_candidate_vacancy", table_name="applications")
    op.drop_table("applications")
    op.drop_index("ix_candidates_resume_provenance", table_name="candidates")
    op.drop_index("ix_candidates_tenant_id", table_name="candidates")
    op.drop_table("candidates")
