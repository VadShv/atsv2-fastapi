"""Application enhancements + comment threads.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-30

JUGO-140: applications — new columns (origin, current_stage_id, stage_entered_at,
          screening_score, risk_level, rejection_reason_code, rejection_reason_label,
          internal_rejection_note, resume_id)
JUGO-143: comment_threads — new table for comment threads on applications
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JUGO-140: расширение таблицы applications
    op.add_column(
        "applications",
        sa.Column("origin", sa.String(30), nullable=False, server_default="incoming"),
    )
    op.add_column(
        "applications",
        sa.Column("current_stage_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("stage_entered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("screening_score", sa.Float, nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="none"),
    )
    op.add_column(
        "applications",
        sa.Column("rejection_reason_code", sa.String(100), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("rejection_reason_label", sa.String(255), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("internal_rejection_note", sa.Text, nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # JUGO-143: таблица comment_threads
    op.create_table(
        "comment_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("observers", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("comments", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_comment_threads_tenant_id", "comment_threads", ["tenant_id"]
    )
    op.create_index(
        "ix_comment_threads_application_id", "comment_threads", ["application_id"]
    )

    # RLS для comment_threads (SECURE FIRST)
    op.execute(
        "ALTER TABLE comment_threads ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY comment_threads_tenant_isolation ON comment_threads "
        "USING (tenant_id = current_setting('app.tenant_id')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS comment_threads_tenant_isolation ON comment_threads")
    op.execute("ALTER TABLE comment_threads DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_comment_threads_application_id", table_name="comment_threads")
    op.drop_index("ix_comment_threads_tenant_id", table_name="comment_threads")
    op.drop_table("comment_threads")

    op.drop_column("applications", "resume_id")
    op.drop_column("applications", "internal_rejection_note")
    op.drop_column("applications", "rejection_reason_label")
    op.drop_column("applications", "rejection_reason_code")
    op.drop_column("applications", "risk_level")
    op.drop_column("applications", "screening_score")
    op.drop_column("applications", "stage_entered_at")
    op.drop_column("applications", "current_stage_id")
    op.drop_column("applications", "origin")

