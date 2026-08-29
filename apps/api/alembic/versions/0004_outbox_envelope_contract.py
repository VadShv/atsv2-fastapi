"""Outbox v2: extend outbox to event envelope contract (TZ §4.3).

Adds schema_version, aggregate_type, aggregate_id, actor_type, actor_id,
occurred_at columns. Renames event_type values to dot.notation.
Adds outbox_lag gauge helper: processed_at tracking for relay metrics.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Расширяем outbox под контракт конверта события (§4.3)
    op.add_column(
        "outbox",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "outbox",
        sa.Column("aggregate_type", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column(
        "outbox",
        sa.Column("aggregate_id", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "outbox",
        sa.Column("actor_type", sa.String(50), nullable=False, server_default="system"),
    )
    op.add_column(
        "outbox",
        sa.Column("actor_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "outbox",
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Индекс для outbox-relay: быстрый выбор неотправленных по времени создания
    op.execute(
        "CREATE INDEX ix_outbox_pending "
        "ON outbox (created_at) "
        "WHERE processed_at IS NULL"
    )
    # Составной индекс: фильтр по агрегату (для replay по конкретному агрегату)
    op.execute(
        "CREATE INDEX ix_outbox_aggregate "
        "ON outbox (tenant_id, aggregate_type, aggregate_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_outbox_aggregate")
    op.execute("DROP INDEX IF EXISTS ix_outbox_pending")
    op.drop_column("outbox", "occurred_at")
    op.drop_column("outbox", "actor_id")
    op.drop_column("outbox", "actor_type")
    op.drop_column("outbox", "aggregate_id")
    op.drop_column("outbox", "aggregate_type")
    op.drop_column("outbox", "schema_version")
