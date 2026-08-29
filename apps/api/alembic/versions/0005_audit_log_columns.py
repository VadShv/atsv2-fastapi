"""Audit log: add user_agent + trace_id columns (TZ §15 observability).

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("user_agent", sa.String(500), nullable=False, server_default=""),
    )
    op.add_column(
        "audit_log",
        sa.Column("trace_id", sa.String(64), nullable=False, server_default=""),
    )
    op.execute("CREATE INDEX ix_audit_log_trace_id ON audit_log (trace_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_log_trace_id")
    op.drop_column("audit_log", "trace_id")
    op.drop_column("audit_log", "user_agent")
