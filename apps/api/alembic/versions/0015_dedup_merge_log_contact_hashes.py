"""Dedup: candidate_contacts + merge_log tables (RLS).

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-30

JUGO-150..155: Дедупликация кандидатов.
  - candidate_contacts — хэши контактов (HMAC-SHA256) для точного поиска дублей
  - merge_log          — журнал мерджей со снапшотом для отката (30 дней)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEDUP_TABLES = ["candidate_contacts", "merge_log"]


def upgrade() -> None:
    # --- candidate_contacts ---
    op.create_table(
        "candidate_contacts",
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
        sa.Column("kind", sa.String(20), nullable=False),  # phone|email|telegram|...
        sa.Column("value_encrypted", postgresql.BYTEA, nullable=True),  # зашифрованное значение
        sa.Column("value_hash", sa.String(128), nullable=False),  # HMAC-SHA256
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "kind",
            "value_hash",
            name="uq_candidate_contacts_tenant_kind_hash",
        ),
    )
    op.create_index(
        "ix_candidate_contacts_value_hash",
        "candidate_contacts",
        ["value_hash"],
    )
    op.create_index(
        "ix_candidate_contacts_candidate_id",
        "candidate_contacts",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_contacts_tenant_id",
        "candidate_contacts",
        ["tenant_id"],
    )

    # --- merge_log ---
    op.create_table(
        "merge_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "survivor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "absorbed_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("merged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),  # снапшот поглощённого кандидата
        sa.Column("status", sa.String(20), nullable=False, server_default="merged"),
        sa.Column(
            "merged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),  # для истечения окна отката
    )
    op.create_index("ix_merge_log_tenant_id", "merge_log", ["tenant_id"])
    op.create_index("ix_merge_log_survivor_id", "merge_log", ["survivor_id"])
    op.create_index("ix_merge_log_absorbed_id", "merge_log", ["absorbed_id"])

    # --- RLS для новых таблиц ---
    for table in DEDUP_TABLES:
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
    for table in reversed(DEDUP_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_write ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_merge_log_absorbed_id", table_name="merge_log")
    op.drop_index("ix_merge_log_survivor_id", table_name="merge_log")
    op.drop_index("ix_merge_log_tenant_id", table_name="merge_log")
    op.drop_table("merge_log")

    op.drop_index("ix_candidate_contacts_tenant_id", table_name="candidate_contacts")
    op.drop_index("ix_candidate_contacts_candidate_id", table_name="candidate_contacts")
    op.drop_index("ix_candidate_contacts_value_hash", table_name="candidate_contacts")
    op.drop_table("candidate_contacts")
