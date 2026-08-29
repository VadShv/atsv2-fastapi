"""Initial schema: tenants, users, roles, vacancies, provenance, outbox, audit, RLS.

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Таблицы с tenant_id — получают RLS-политики
TENANT_TABLES = [
    "vacancies",
    "pipeline_stages",
    "provenance",
    "outbox",
    "audit_log",
    "roles",
    "users",
]


def upgrade() -> None:
    # Расширения
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- tenants (корень изоляции) ---
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- roles ---
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("permissions", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name_encrypted", sa.Text, nullable=False, server_default=""),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role_id", "users", ["role_id"])

    # --- provenance (whitebox AI) ---
    op.create_table(
        "provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill", sa.String(100), nullable=False),
        sa.Column("prompt_id", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_refs", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("raw_output", sa.Text, nullable=False),
        sa.Column("parsed_output", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False),
        sa.Column("tokens_out", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("human_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reasoning_trace", sa.Text, nullable=False, server_default=""),
        sa.Column("non_ai", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_provenance_tenant_id", "provenance", ["tenant_id"])
    op.create_index("ix_provenance_skill", "provenance", ["skill"])
    op.create_index("ix_provenance_input_hash", "provenance", ["input_hash"])

    # --- vacancies ---
    op.create_table(
        "vacancies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("seniority", sa.String(50), nullable=False),
        sa.Column("team", sa.String(200), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("role_description", sa.Text, nullable=False),
        sa.Column("requirements", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("nice_to_have", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("screening_criteria_provenance", postgresql.UUID(as_uuid=True), sa.ForeignKey("provenance.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vacancies_tenant_id", "vacancies", ["tenant_id"])

    # --- pipeline_stages ---
    op.create_table(
        "pipeline_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vacancy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vacancies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("stage_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pipeline_stages_tenant_id", "pipeline_stages", ["tenant_id"])
    op.create_index("ix_pipeline_stages_vacancy_id", "pipeline_stages", ["vacancy_id"])

    # --- outbox (устойчивость) ---
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_outbox_tenant_id", "outbox", ["tenant_id"])
    op.create_index("ix_outbox_event_type", "outbox", ["event_type"])
    op.create_index(
        "ix_outbox_unprocessed",
        "outbox",
        ["processed_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    # --- audit_log (secure-first, immutable) ---
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])

    # --- Векторная колонка для поиска кандидатов (заготовка под Фазу 3) ---
    op.execute("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS embedding vector(1536)")

    # --- RLS: изоляция тенантов (SECURE FIRST) ---
    _apply_rls()


def _apply_rls() -> None:
    """Включить RLS и создать политики для всех tenant-таблиц.

    Политика: строка видна/изменяется только если tenant_id = app.tenant_id (GUC).
    app.tenant_id выставляется в сессии на каждый запрос.
    """
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # USING: фильтр при SELECT
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )
        # WITH CHECK: проверка при INSERT/UPDATE
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

    op.drop_table("audit_log")
    op.drop_table("outbox")
    op.drop_table("pipeline_stages")
    op.drop_table("vacancies")
    op.drop_table("provenance")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("tenants")
