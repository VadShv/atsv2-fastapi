"""M1 Screening: m1_screening_results table (RLS).

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-30

JUGO-400: karakas modulya m1_screening.
  - m1_screening_results — rezultaty skrininga kandidata po kriteriyam vakansii
    (total_score, recommendation, evaluations JSONB, level0 JSONB, provenance)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "m1_screening_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
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
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("total_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("recommendation", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("evaluations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("level0", postgresql.JSONB, nullable=True),
        sa.Column("provenance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("criteria_provenance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("non_ai", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("overridden_by", sa.String(100), nullable=False, server_default=""),
        sa.Column("override_action", sa.String(20), nullable=True),
        sa.Column("is_stale", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_m1_screening_results_tenant_id",
        "m1_screening_results",
        ["tenant_id"],
    )
    op.create_index(
        "ix_m1_screening_results_application_id",
        "m1_screening_results",
        ["application_id"],
    )
    op.create_index(
        "ix_m1_screening_results_vacancy_id",
        "m1_screening_results",
        ["vacancy_id"],
    )
    op.create_index(
        "ix_m1_screening_results_candidate_id",
        "m1_screening_results",
        ["candidate_id"],
    )
    op.create_index(
        "ix_m1_screening_results_is_stale",
        "m1_screening_results",
        ["is_stale"],
    )

    # RLS for m1_screening_results
    op.execute("ALTER TABLE m1_screening_results ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY m1_screening_results_tenant_isolation ON m1_screening_results "
        "USING (tenant_id = app.tenant_id())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS m1_screening_results_tenant_isolation ON m1_screening_results")
    op.execute("ALTER TABLE m1_screening_results DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_m1_screening_results_is_stale", table_name="m1_screening_results")
    op.drop_index("ix_m1_screening_results_candidate_id", table_name="m1_screening_results")
    op.drop_index("ix_m1_screening_results_vacancy_id", table_name="m1_screening_results")
    op.drop_index("ix_m1_screening_results_application_id", table_name="m1_screening_results")
    op.drop_index("ix_m1_screening_results_tenant_id", table_name="m1_screening_results")
    op.drop_table("m1_screening_results")
