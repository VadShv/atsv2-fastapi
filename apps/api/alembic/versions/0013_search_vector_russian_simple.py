"""Search: tsvector config russian,simple + search_synonyms table.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-30

JUGO-170: Переключение search_tsv на to_tsvector('russian,simple', ...)
          — simple-конфиг индексирует латиницу/цифры без стемминга,
            russian — стемминг для кириллицы. Комбинация даёт точный
            поиск по обоим алфавитам.
JUGO-172: Таблица search_synonyms (term, synonyms[], tenant_id) с RLS
          — словарь синонимов для расширения запросов.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- JUGO-170: tsvector config russian,simple ---
    # Перегенерируем search_tsv с новым конфигом для всех существующих записей.
    op.execute(
        """
        UPDATE candidates_search
        SET search_tsv = to_tsvector('russian,simple', search_text)
        """
    )

    # --- JUGO-172: search_synonyms table ---
    op.create_table(
        "search_synonyms",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column(
            "synonyms",
            sa.dialects.postgresql.ARRAY(sa.String(255)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Уникальный индекс (term per tenant)
    op.execute(
        "CREATE UNIQUE INDEX ux_search_synonyms_tenant_term "
        "ON search_synonyms (tenant_id, lower(term))"
    )
    op.execute("CREATE INDEX ix_search_synonyms_tenant ON search_synonyms (tenant_id)")

    # RLS (SECURE FIRST)
    op.execute("ALTER TABLE search_synonyms ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE search_synonyms FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON search_synonyms "
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_write ON search_synonyms "
        "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_write ON search_synonyms")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON search_synonyms")
    op.execute("ALTER TABLE search_synonyms NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE search_synonyms DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_search_synonyms_tenant")
    op.execute("DROP INDEX IF EXISTS ux_search_synonyms_tenant_term")
    op.drop_table("search_synonyms")

    # Откат tsvector к russian-only
    op.execute(
        """
        UPDATE candidates_search
        SET search_tsv = to_tsvector('russian', search_text)
        """
    )
