"""Postgres + pgvector поисковый движок (production).

БЫСТРЕЙШИЙ ПОИСК: гибридный BM25 (tsvector) ⊕ vector (pgvector cosine) ⊕ фильтры.
Собирается из SQL-функций ранжирования PostgreSQL, всё через параметризованные
запросы SQLAlchemy (SECURE FIRST: никаких f-string в SQL).

Таблица candidates_search содержит: tenant_id, candidate_id, search_text,
search_tsv (tsvector), embedding (halfvec), metadata (jsonb).

Размерность: эмбеддинги 4096, HNSW-индекс на halfvec(4000) — pgvector лимит.
Обрезка 4096→4000 в _vec_to_pg (потеря 2.3%, незначительно).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ats.infra.db.session import get_session_factory
from ats.modules.search.domain.models import (
    Facet,
    FacetValue,
    SearchableDocument,
    SearchFilter,
    SearchHit,
    SearchQuery,
    SearchResult,
)
from ats.modules.search.ports.search_engine import SearchEngine

logger = logging.getLogger(__name__)

# pgvector: halfvec поддерживает до 4000 dim с HNSW-индексом.
# Эмбеддинги 4096 обрезаются до 4000 (потеря 2.3%, см. миграцию 0006).
PGVECTOR_INDEX_DIM = 4000


class PgVectorSearchEngine(SearchEngine):
    """Production-адаптер поиска на Postgres + pgvector.

    RLS: фильтрация по tenant_id на уровне сессии (app.tenant_id GUC).
    """

    def __init__(self) -> None:
        self._session_factory = get_session_factory()

    async def index(self, document: SearchableDocument) -> None:
        async with self._session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO candidates_search
                        (tenant_id, candidate_id, search_text, search_tsv,
                         embedding, metadata)
                    VALUES
                        (:tenant_id, :candidate_id, :search_text,
                         to_tsvector('russian', :search_text),
                         CAST(:embedding AS halfvec(4000)),
                         CAST(:metadata AS jsonb))
                    ON CONFLICT (tenant_id, candidate_id) DO UPDATE SET
                        search_text = EXCLUDED.search_text,
                        search_tsv = EXCLUDED.search_tsv,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata
                    """
                ),
                {
                    "tenant_id": str(document.tenant_id),
                    "candidate_id": str(document.id),
                    "search_text": document.text,
                    "embedding": _vec_to_pg(document.embedding),
                    "metadata": _json_to_pg(document.metadata),
                },
            )
            await session.commit()

    async def remove(self, tenant_id, document_id) -> None:  # type: ignore[no-untyped-def]
        async with self._session() as session:
            await session.execute(
                text(
                    "DELETE FROM candidates_search "
                    "WHERE tenant_id = :tenant_id AND candidate_id = :candidate_id"
                ),
                {
                    "tenant_id": str(tenant_id),
                    "candidate_id": str(document_id),
                },
            )
            await session.commit()

    async def search(self, query: SearchQuery) -> SearchResult:
        start = time.monotonic()
        embedding_sql = _vec_to_pg(query.query_embedding)
        bm25_w = query.bm25_weight
        vec_w = query.vector_weight if query.query_embedding else 0.0

        where_clauses = ["tenant_id = CAST(:tenant_id AS uuid)"]
        params: dict[str, Any] = {
            "tenant_id": str(query.tenant_id),
            "q_text": query.query,
            "embedding": embedding_sql,
            "limit": query.limit,
            "offset": query.offset,
            "bm25_w": bm25_w,
            "vec_w": vec_w,
        }
        where_clauses.extend(_build_filter_sql(query.filters, params))

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                candidate_id,
                ts_rank(search_tsv, plainto_tsquery('russian', :q_text)) AS bm25_score,
                CASE WHEN :embedding IS NULL THEN 0.0
                     ELSE 1 - (embedding <=> CAST(:embedding AS halfvec(4000))) END AS vec_score,
                (:bm25_w * ts_rank(search_tsv, plainto_tsquery('russian', :q_text))
                 + :vec_w * CASE WHEN :embedding IS NULL THEN 0.0
                                 ELSE 1 - (embedding <=> CAST(:embedding AS halfvec(4000))) END
                ) AS final_score,
                search_text,
                metadata
            FROM candidates_search
            WHERE {where_sql}
            ORDER BY final_score DESC
            LIMIT :limit OFFSET :offset
        """

        async with self._session() as session:
            rows = (await session.execute(text(sql), params)).fetchall()

        total_sql = f"""
            SELECT count(*) FROM candidates_search WHERE {where_sql}
        """
        # Для count-запроса убираем limit/offset из параметров — пересоздаём
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        async with self._session() as session:
            total = (await session.execute(text(total_sql), count_params)).scalar() or 0

        hits = [
            SearchHit(
                document_id=UUID(str(row.candidate_id)),
                score=float(row.final_score),
                bm25_score=float(row.bm25_score),
                vector_score=float(row.vec_score),
                metadata=row.metadata or {},
                snippet=(row.search_text or "")[:160],
            )
            for row in rows
        ]

        facets = await self._facets(query)

        took_ms = int((time.monotonic() - start) * 1000)
        return SearchResult(
            hits=hits,
            total=int(total),
            facets=facets,
            took_ms=took_ms,
            query=query.query,
        )

    async def _facets(self, query: SearchQuery) -> list[Facet]:
        if not query.facet_fields:
            return []
        result: list[Facet] = []
        async with self._session() as session:
            for field in query.facet_fields:
                sql = text(
                    """
                    SELECT facet_value, count(*) AS cnt FROM (
                        SELECT jsonb_array_elements_text(
                            COALESCE(metadata->:field, '[]'::jsonb)
                        ) AS facet_value
                        FROM candidates_search
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                    ) sub
                    WHERE facet_value IS NOT NULL
                    GROUP BY facet_value ORDER BY cnt DESC
                    """
                )
                rows = (
                    await session.execute(sql, {"field": field, "tenant_id": str(query.tenant_id)})
                ).fetchall()
                result.append(
                    Facet(
                        field=field,
                        values=[
                            FacetValue(value=str(r.facet_value), count=int(r.cnt)) for r in rows
                        ],
                    )
                )
        return result

    def _session(self):
        return self._session_factory()


def _build_filter_sql(filters: list[SearchFilter], params: dict[str, Any]) -> list[str]:
    clauses: list[str] = []
    for i, f in enumerate(filters):
        key = f"filter_{i}"
        if f.operator in ("any", "all"):
            op = "?|" if f.operator == "any" else "?&"
            clauses.append(
                f"COALESCE(metadata->'{f.field}', '[]'::jsonb) {op} CAST(:{key} AS jsonb)"
            )
            params[key] = _json_to_pg(f.values)
        elif f.operator == "gte":
            clauses.append(f"(metadata->>'{f.field}')::float >= :{key}")
            params[key] = float(f.values[0]) if f.values else 0.0
        elif f.operator == "lte":
            clauses.append(f"(metadata->>'{f.field}')::float <= :{key}")
            params[key] = float(f.values[0]) if f.values else 0.0
    return clauses


def _vec_to_pg(vec: list[float] | None) -> str | None:
    """Конвертация вектора в PG-строку с обрезкой до PGVECTOR_INDEX_DIM.

    pgvector HNSW на halfvec поддерживает max 4000 dim. Эмбеддинги 4096
    обрезаются до 4000 (потеря 2.3%, см. миграцию 0006).
    """
    if vec is None:
        return None
    truncated = vec[:PGVECTOR_INDEX_DIM]
    return "[" + ",".join(str(v) for v in truncated) + "]"


def _json_to_pg(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
