"""Funnel: presets, snapshots, transitions, HM decisions, automation rules.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-30

JUGO-130: funnel_presets + funnel_stages (JSONB)
JUGO-131: funnel_snapshots — immutable snapshot per vacancy
JUGO-132: stage_transitions — append-only journal
JUGO-134: hm_decisions — immutable HM decisions
JUGO-135: stage_automation_rules — automation rule framework
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JUGO-130: funnel_presets
    op.create_table(
        "funnel_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("stages", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_funnel_presets_tenant_id", "funnel_presets", ["tenant_id"])

    # RLS for funnel_presets
    op.execute("ALTER TABLE funnel_presets ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY funnel_presets_tenant_isolation ON funnel_presets "
        "USING (tenant_id = app.tenant_id())"
    )

    # JUGO-131: funnel_snapshots (immutable, one per vacancy)
    op.create_table(
        "funnel_snapshots",
        sa.Column("vacancy_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stages", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vacancy_id"], ["vacancies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preset_id"], ["funnel_presets.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_funnel_snapshots_tenant_id", "funnel_snapshots", ["tenant_id"])
    op.execute("ALTER TABLE funnel_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY funnel_snapshots_tenant_isolation ON funnel_snapshots "
        "USING (tenant_id = app.tenant_id())"
    )

    # JUGO-132: stage_transitions (append-only)
    op.create_table(
        "stage_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_stage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("actor_type", sa.String(50), nullable=False, server_default="user"),
        sa.Column("ai_provenance", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_stage_transitions_tenant_id", "stage_transitions", ["tenant_id"])
    op.create_index("ix_stage_transitions_application_id", "stage_transitions", ["application_id"])
    op.execute("ALTER TABLE stage_transitions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY stage_transitions_tenant_isolation ON stage_transitions "
        "USING (tenant_id = app.tenant_id())"
    )

    # JUGO-134: hm_decisions (immutable)
    op.create_table(
        "hm_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("justification", sa.Text, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_hm_decisions_tenant_id", "hm_decisions", ["tenant_id"])
    op.create_index("ix_hm_decisions_application_id", "hm_decisions", ["application_id"])
    op.execute("ALTER TABLE hm_decisions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY hm_decisions_tenant_isolation ON hm_decisions "
        "USING (tenant_id = app.tenant_id())"
    )

    # JUGO-135: stage_automation_rules
    op.create_table(
        "stage_automation_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("condition", sa.String(100), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("params", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("block_auto_reject", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_stage_automation_rules_tenant_id", "stage_automation_rules", ["tenant_id"])
    op.create_index("ix_stage_automation_rules_stage_id", "stage_automation_rules", ["stage_id"])
    op.execute("ALTER TABLE stage_automation_rules ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY stage_automation_rules_tenant_isolation ON stage_automation_rules "
        "USING (tenant_id = app.tenant_id())"
    )


def downgrade() -> None:
    op.drop_table("stage_automation_rules")
    op.drop_table("hm_decisions")
    op.drop_table("stage_transitions")
    op.drop_table("funnel_snapshots")
    op.drop_table("funnel_presets")
