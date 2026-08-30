"""Vacancy enhancements + requirement sets.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-30

JUGO-120: vacancies — add hiring_team, hired_count, closed_at columns
JUGO-121: vacancy_requirement_sets — versioned screening criteria table
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JUGO-120: add new columns to vacancies
    op.add_column("vacancies", sa.Column("hiring_team", sa.String(200), nullable=False, server_default=""))
    op.add_column("vacancies", sa.Column("hired_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("vacancies", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))

    # JUGO-121: vacancy_requirement_sets — versioned criteria
    op.create_table(
        "vacancy_requirement_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vacancy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vacancies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("criteria", postgresql.JSONB(), nullable=False),
        sa.Column("origin", sa.String(50), nullable=False, server_default="ai"),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column(
            "provenance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provenance.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_vacancy_requirement_sets_tenant_id",
        "vacancy_requirement_sets",
        ["tenant_id"],
    )
    op.create_index(
        "ix_vacancy_requirement_sets_vacancy_id",
        "vacancy_requirement_sets",
        ["vacancy_id"],
    )
    # Only one active version per vacancy
    op.create_index(
        "ux_requirement_sets_vacancy_active",
        "vacancy_requirement_sets",
        ["tenant_id", "vacancy_id", "status"],
        postgresql_where=sa.text("status = 'active'"),
        unique=True,
    )

    # RLS
    op.execute("ALTER TABLE vacancy_requirement_sets ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_requirement_sets ON vacancy_requirement_sets "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_requirement_sets ON vacancy_requirement_sets")
    op.execute("ALTER TABLE vacancy_requirement_sets DISABLE ROW LEVEL SECURITY")
    op.drop_index("ux_requirement_sets_vacancy_active", table_name="vacancy_requirement_sets")
    op.drop_index("ix_vacancy_requirement_sets_vacancy_id", table_name="vacancy_requirement_sets")
    op.drop_index("ix_vacancy_requirement_sets_tenant_id", table_name="vacancy_requirement_sets")
    op.drop_table("vacancy_requirement_sets")

    op.drop_column("vacancies", "closed_at")
    op.drop_column("vacancies", "hired_count")
    op.drop_column("vacancies", "hiring_team")
