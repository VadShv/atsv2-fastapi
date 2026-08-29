"""Search: candidates_search table with tsvector + pgvector + jsonb facets.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "candidates_search",
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "candidate_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("search_text", sa.Text, nullable=False, server_default=""),
        sa.Column("search_tsv", sa.dialects.postgresql.TSVECTOR, nullable=False),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )

    # GIN-индекс для полнотекстового поиска (СКОРОСТЬ)
    op.execute(
        "CREATE INDEX ix_cs_search_tsv ON candidates_search USING gin(search_tsv)"
    )
    # ivfflat-индекс для векторного поиска (БЫСТРЕЙШИЙ ПОИСК)
    op.execute(
        "CREATE INDEX ix_cs_embedding ON candidates_search "
        "USING ivfflat(CAST(embedding AS vector(1536)) vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute("CREATE INDEX ix_cs_tenant_id ON candidates_search (tenant_id)")
    op.execute(
        "CREATE INDEX ix_cs_metadata ON candidates_search USING gin(metadata)"
    )

    # RLS (SECURE FIRST)
    op.execute("ALTER TABLE candidates_search ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE candidates_search FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON candidates_search "
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_write ON candidates_search "
        "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_write ON candidates_search")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON candidates_search")
    op.execute("ALTER TABLE candidates_search NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE candidates_search DISABLE ROW LEVEL SECURITY")
    op.drop_table("candidates_search")
