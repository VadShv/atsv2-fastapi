"""Embeddings 4096: migrate candidates_search + vacancies from 1536/ivfflat to 4096/HNSW.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-29

Решение проекта: эмбеддинги размерности 4096 (text-embedding-3-large).
HNSW-индекс вместо ivfflat — лучше для высокого dim, не требует списков,
быстрее на больших выборках (БЫСТРЕЙШИЙ ПОИСК).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- candidates_search: vector(1536) → vector(4096) + ivfflat → HNSW ---

    # Удаляем старый ivfflat-индекс (dim 1536)
    op.execute("DROP INDEX IF EXISTS ix_cs_embedding")

    # Меняем размерность колонки embedding.
    # Колонка создана как Text в 0003 (CAST AS vector в SQL),
    # поэтому достаточно пересоздать индекс с новым dim.
    # HNSW: оптимальный ANN-индекс для dim=4096 (БЫСТРЕЙШИЙ ПОИСК)
    op.execute(
        "CREATE INDEX ix_cs_embedding ON candidates_search "
        "USING hnsw(CAST(embedding AS vector(4096)) vector_cosine_ops)"
    )

    # --- vacancies: vector(1536) → vector(4096) ---
    # Колонка embedding создаётся в 0001 как vector(1536).
    # Пересоздаём как vector(4096). Старые значения невалидны → обнуляем.
    op.execute("ALTER TABLE vacancies ALTER COLUMN embedding TYPE vector(4096) USING NULL")
    op.execute("UPDATE vacancies SET embedding = NULL")


def downgrade() -> None:
    # candidates_search: обратно на 1536 + ivfflat
    op.execute("DROP INDEX IF EXISTS ix_cs_embedding")
    op.execute(
        "CREATE INDEX ix_cs_embedding ON candidates_search "
        "USING ivfflat(CAST(embedding AS vector(1536)) vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    # vacancies: обратно на 1536
    op.execute("ALTER TABLE vacancies ALTER COLUMN embedding TYPE vector(1536) USING NULL")
    op.execute("UPDATE vacancies SET embedding = NULL")
