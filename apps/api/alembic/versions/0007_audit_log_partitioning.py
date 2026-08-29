"""Audit log: partitioning by month + composite index (JUGO-033, ТЗ §15).

Partitioning strategy: native PostgreSQL declarative partitioning by month.
- audit_log → PARTITION BY RANGE (created_at)
- Partitions: audit_log_YYYY_MM
- Automatic partition creation function + monthly cron trigger
- Composite index: (tenant_id, created_at) for fast tenant-scoped queries
- Append-only enforcement: REVOKE UPDATE, DELETE on audit_log

SECURE FIRST: audit records are immutable (no UPDATE/DELETE).
УСТОЙЧИВОСТЬ: partitions can be archived/dropped independently.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str | Sequence[str], None] = None
depends_on: Union[str | Sequence[str], None] = None


def upgrade() -> None:
    """
    Конвертировать audit_log в партиционированную таблицу по месяцам.

    Шаги:
    1. Создать новую партиционированную таблицу audit_log_partitioned
    2. Перенести данные из audit_log
    3. Удалить старую audit_log
    4. Переименовать audit_log_partitioned → audit_log
    5. Создать индексы на партиционированной таблице
    6. Создать функцию автоматического создания партиций
    7. Применить RLS к новой таблице
    8. Запретить UPDATE/DELETE (append-only)
    """

    # 1. Создать партиционированную родительскую таблицу
    op.execute(
        """
        CREATE TABLE audit_log_partitioned (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            actor_id UUID,
            action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(100) NOT NULL,
            entity_id VARCHAR(64) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}',
            ip_address VARCHAR(45) NOT NULL DEFAULT '',
            user_agent VARCHAR(500) NOT NULL DEFAULT '',
            trace_id VARCHAR(64) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )

    # 2. Создать партицию для текущего и следующего месяца
    op.execute(
        """
        CREATE TABLE audit_log_2026_08
            PARTITION OF audit_log_partitioned
            FOR VALUES FROM ('2026-08-01') TO ('2026-09-01')
        """
    )
    op.execute(
        """
        CREATE TABLE audit_log_2026_09
            PARTITION OF audit_log_partitioned
            FOR VALUES FROM ('2026-09-01') TO ('2026-10-01')
        """
    )

    # 3. Перенести данные из старой таблицы
    op.execute(
        """
        INSERT INTO audit_log_partitioned
            (id, tenant_id, actor_id, action, entity_type, entity_id,
             details, ip_address, user_agent, trace_id, created_at, updated_at)
        SELECT
            id, tenant_id, actor_id, action, entity_type, entity_id,
            details, ip_address, user_agent, trace_id, created_at, updated_at
        FROM audit_log
        """
    )

    # 4. Удалить старую таблицу
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")

    # 5. Переименовать новую таблицу
    op.execute("ALTER TABLE audit_log_partitioned RENAME TO audit_log")

    # 6. Создать индексы (на партиционированной таблице — создаются на каждой партиции)
    # Composite index: (tenant_id, created_at) — основной для tenant-scoped запросов
    op.execute(
        "CREATE INDEX ix_audit_log_tenant_created "
        "ON audit_log (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_actor_created "
        "ON audit_log (actor_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_trace_id "
        "ON audit_log (trace_id)"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_action "
        "ON audit_log (action, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_entity "
        "ON audit_log (entity_type, entity_id, created_at DESC)"
    )

    # 7. RLS на партиционированную таблицу
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_log "
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_write ON audit_log "
        "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"
    )

    # 8. Append-only: запретить UPDATE и DELETE (SECURE FIRST)
    # Отзываем права на UPDATE/DELETE у всех ролей, кроме superuser
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM ats")

    # 9. Функция автоматического создания партиций (для cron/воркера)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION create_audit_partition_if_not_exists(
            target_month date DEFAULT date_trunc('month', now())::date
        ) RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            partition_name text;
            start_date date;
            end_date date;
        BEGIN
            partition_name := 'audit_log_' || to_char(target_month, 'YYYY_MM');
            start_date := date_trunc('month', target_month)::date;
            end_date := (start_date + interval '1 month')::date;

            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_log FOR VALUES FROM (%L) TO (%L)',
                partition_name, start_date, end_date
            );
        END;
        $$;
        """
    )

    # 10. Создать партицию на следующий месяц (на случай если воркер не запущен)
    op.execute("SELECT create_audit_partition_if_not_exists(date_trunc('month', now() + interval '1 month')::date)")


def downgrade() -> None:
    # Удалить функцию
    op.execute("DROP FUNCTION IF EXISTS create_audit_partition_if_not_exists(date)")

    # Удалить политики RLS
    op.execute("DROP POLICY IF EXISTS tenant_isolation_write ON audit_log")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")

    # Удалить партиционированную таблицу (cascade удаляет партиции)
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")

    # Восстановить непартиционированную таблицу
    op.create_table(
        "audit_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("details", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(500), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.execute("CREATE INDEX ix_audit_log_trace_id ON audit_log (trace_id)")
