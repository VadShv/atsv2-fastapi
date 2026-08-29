"""Embeddings 4096: migrate candidates_search + vacancies from 1536/ivfflat to 4096.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-29

Решение проекта: эмбеддинги размерности 4096 (text-embedding-3-large).

Ограничение pgvector: HNSW/ivfflat индексы поддерживают max 2000 dim для vector
и max 4000 dim для halfvec. Поскольку 4096 > 4000, используем halfvec(4000) с
обрезкой до 4000 измерений (потеря 96 из 4096 = 2.3%, незначительно для качества).
HNSW на halfvec — оптимальный ANN-индекс (БЫСТРЕЙШИЙ ПОИСК).

Для масштабирования на production можно добавить binary quantization (bit type,
до 64000 dim) как второй индекс.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# pgvector: halfvec поддерживает до 4000 dim с HNSW
PGVECTOR_INDEX_DIM = 4000


def upgrade() -> None:
    # --- candidates_search: vector(1536)/ivfflat → halfvec(4000)/HNSW ---

    # Удаляем старый ivfflat-индекс (dim 1536)
    op.execute("DROP INDEX IF EXISTS ix_cs_embedding")

    # HNSW на halfvec(4000): максимальная размерность для ANN-индекса в pgvector.
    # Колонка embedding — Text, CAST AS halfvec(4000) в SQL.
    # Обрезка 4096→4000 выполняется в коде (gateway truncate_to_pgvector_dim).
    op.execute(
        "CREATE INDEX ix_cs_embedding ON candidates_search "
        "USING hnsw(CAST(embedding AS halfvec(4000)) halfvec_cosine_ops)"
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
