"""Organization: legal_entities + org_units tables (ltree, RLS).

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-30

JUGO-200: Модели legal_entities, org_units (дерево ltree, защита от циклов,
          архивирование вместо удаления) + привязка вакансии.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG_TABLES = ["legal_entities", "org_units"]


def upgrade() -> None:
    # Расширение ltree для иерархических путей
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    # --- legal_entities ---
    op.create_table(
        "legal_entities",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="other"),
        sa.Column("inn", sa.String(20), nullable=False, server_default=""),
        sa.Column("full_name", sa.String(1000), nullable=False, server_default=""),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_legal_entities_tenant_id", "legal_entities", ["tenant_id"])
    op.create_index(
        "ix_legal_entities_tenant_name",
        "legal_entities",
        ["tenant_id", "name"],
        unique=True,
    )

    # --- org_units (дерево через ltree path) ---
    op.create_table(
        "org_units",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "legal_entity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("parent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        # ltree-путь: uuid с дефисами заменены на подчёркивания
        sa.Column("path", sa.dialects.postgresql.TEXT, nullable=False),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_org_units_tenant_id", "org_units", ["tenant_id"])
    op.create_index("ix_org_units_legal_entity_id", "org_units", ["legal_entity_id"])
    op.create_index("ix_org_units_parent_id", "org_units", ["parent_id"])

    # Самоссылающийся FK для parent_id
    op.create_foreign_key(
        "fk_org_units_parent_id",
        "org_units",
        "org_units",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ltree: приводим path к типу ltree и создаём GIST-индекс для быстрого поиска поддеревьев.
    # Имя ltree-метки: латиница + цифры + подчёркивание. UUID → uuid_с_подчёркиваниями.
    op.execute("ALTER TABLE org_units ALTER COLUMN path TYPE ltree USING path::ltext::ltree")
    op.execute(
        "CREATE INDEX ix_org_units_path_gist ON org_units USING GIST (path)"
    )

    # --- Привязка вакансии к юрлицу и подразделению (JUGO-200) ---
    # Добавляем nullable-колонки в vacancies (ТЗ §5.1).
    op.add_column(
        "vacancies",
        sa.Column("legal_entity_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "vacancies",
        sa.Column("org_unit_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_vacancies_legal_entity_id",
        "vacancies",
        "legal_entities",
        ["legal_entity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_vacancies_org_unit_id",
        "vacancies",
        "org_units",
        ["org_unit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_vacancies_legal_entity_id", "vacancies", ["legal_entity_id"])
    op.create_index("ix_vacancies_org_unit_id", "vacancies", ["org_unit_id"])

    # --- RLS для новых таблиц ---
    for table in ORG_TABLES:
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

    # Триггер для автоматического обновления updated_at
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_org_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_legal_entities_updated_at
        BEFORE UPDATE ON legal_entities
        FOR EACH ROW EXECUTE FUNCTION update_org_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_org_units_updated_at
        BEFORE UPDATE ON org_units
        FOR EACH ROW EXECUTE FUNCTION update_org_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_org_units_updated_at ON org_units")
    op.execute("DROP TRIGGER IF EXISTS trg_legal_entities_updated_at ON legal_entities")
    op.execute("DROP FUNCTION IF EXISTS update_org_updated_at()")

    for table in reversed(ORG_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_write ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_vacancies_org_unit_id", table_name="vacancies")
    op.drop_index("ix_vacancies_legal_entity_id", table_name="vacancies")
    op.drop_constraint("fk_vacancies_org_unit_id", "vacancies", type_="foreignkey")
    op.drop_constraint("fk_vacancies_legal_entity_id", "vacancies", type_="foreignkey")
    op.drop_column("vacancies", "org_unit_id")
    op.drop_column("vacancies", "legal_entity_id")

    op.execute("DROP INDEX IF EXISTS ix_org_units_path_gist")
    op.drop_index("ix_org_units_parent_id", table_name="org_units")
    op.drop_index("ix_org_units_legal_entity_id", table_name="org_units")
    op.drop_index("ix_org_units_tenant_id", table_name="org_units")
    op.drop_table("org_units")

    op.drop_index("ix_legal_entities_tenant_name", table_name="legal_entities")
    op.drop_index("ix_legal_entities_tenant_id", table_name="legal_entities")
    op.drop_table("legal_entities")
