"""Candidate facts, tags, blacklist + location column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = ["candidate_facts", "candidate_tags", "candidate_blacklist"]


def upgrade() -> None:
    # 1. Добавить колонку location в candidates
    op.add_column(
        "candidates",
        sa.Column("location", sa.String(500), nullable=False, server_default=""),
    )

    # 2. candidate_facts — структурированные факты профиля
    op.create_table(
        "candidate_facts",
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
        sa.Column("fact_type", sa.String(50), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_candidate_facts_tenant_id", "candidate_facts", ["tenant_id"])
    op.create_index("ix_candidate_facts_candidate_id", "candidate_facts", ["candidate_id"])
    op.create_index(
        "ix_candidate_facts_lookup",
        "candidate_facts",
        ["tenant_id", "candidate_id", "fact_type"],
    )

    # 3. candidate_tags — пользовательские теги
    op.create_table(
        "candidate_tags",
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
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default="#6b7280"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_candidate_tags_tenant_id", "candidate_tags", ["tenant_id"])
    op.create_index("ix_candidate_tags_candidate_id", "candidate_tags", ["candidate_id"])

    # 4. candidate_blacklist — жёсткие блокировки
    op.create_table(
        "candidate_blacklist",
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
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_candidate_blacklist_tenant_id", "candidate_blacklist", ["tenant_id"])
    op.create_index("ix_candidate_blacklist_candidate_id", "candidate_blacklist", ["candidate_id"])
    op.create_index(
        "ux_candidate_blacklist_candidate",
        "candidate_blacklist",
        ["tenant_id", "candidate_id"],
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

    op.drop_index("ux_candidate_blacklist_candidate", table_name="candidate_blacklist")
    op.drop_index("ix_candidate_blacklist_candidate_id", table_name="candidate_blacklist")
    op.drop_index("ix_candidate_blacklist_tenant_id", table_name="candidate_blacklist")
    op.drop_table("candidate_blacklist")

    op.drop_index("ix_candidate_tags_candidate_id", table_name="candidate_tags")
    op.drop_index("ix_candidate_tags_tenant_id", table_name="candidate_tags")
    op.drop_table("candidate_tags")

    op.drop_index("ix_candidate_facts_lookup", table_name="candidate_facts")
    op.drop_index("ix_candidate_facts_candidate_id", table_name="candidate_facts")
    op.drop_index("ix_candidate_facts_tenant_id", table_name="candidate_facts")
    op.drop_table("candidate_facts")

    op.drop_column("candidates", "location")
