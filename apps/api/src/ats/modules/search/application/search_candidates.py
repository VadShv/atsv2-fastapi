"""Use case: гибридный поиск кандидатов.

БЫСТРЕЙШИЙ ПОИСК: текст + эмбеддинг запроса → SearchEngine.search() с фильтрами/фасетами.
WHITEBOX: результат содержит разложение баллов (bm25_score, vector_score).
"""

from __future__ import annotations

import logging

from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.search.domain.models import (
    SearchFilter,
    SearchQuery,
    SearchResult,
)
from ats.modules.search.ports.search_engine import SearchEngine
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


class SearchCandidatesInput:
    """Входные DTO поиска кандидатов."""

    def __init__(
        self,
        query: str,
        filters: list[SearchFilter] | None = None,
        limit: int = 20,
        offset: int = 0,
        facet_fields: list[str] | None = None,
        bm25_weight: float = 0.4,
        vector_weight: float = 0.6,
        skip_embedding: bool = False,
    ) -> None:
        self.query = query
        self.filters = filters or []
        self.limit = limit
        self.offset = offset
        self.facet_fields = facet_fields or []
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.skip_embedding = skip_embedding


class SearchCandidatesUseCase:
    """Поиск кандидатов по тексту запроса + семантике.

    Поток:
    1. Генерация эмбеддинга запроса через AIGateway.embed().
    2. Гибридный поиск в SearchEngine (BM25 ⊕ vector ⊕ фильтры → re-rank).
    3. Возврат SearchResult с фасетами и метриками.
    """

    def __init__(
        self,
        search_engine: SearchEngine,
        ai_gateway: AIGateway,
    ) -> None:
        self._search_engine = search_engine
        self._ai_gateway = ai_gateway

    async def execute(
        self,
        tenant_id: TenantId,
        input_dto: SearchCandidatesInput,
    ) -> Result[SearchResult]:
        if not input_dto.query.strip():
            return Result.err(ErrorCode.VALIDATION, "Пустой поисковый запрос")

        # Эмбеддинг запроса (graceful degradation: без него — только BM25)
        query_embedding: list[float] | None = None
        if not input_dto.skip_embedding:
            try:
                query_embedding = await self._ai_gateway.embed(tenant_id, input_dto.query)
            except Exception as exc:
                logger.warning("Query embedding failed, falling back to BM25-only: %s", exc)

        search_query = SearchQuery(
            tenant_id=tenant_id.value,
            query=input_dto.query,
            query_embedding=query_embedding,
            filters=input_dto.filters,
            limit=input_dto.limit,
            offset=input_dto.offset,
            bm25_weight=input_dto.bm25_weight,
            vector_weight=input_dto.vector_weight,
            facet_fields=input_dto.facet_fields,
        )

        try:
            result = await self._search_engine.search(search_query)
        except Exception as exc:
            logger.error("Search failed: %s", exc)
            return Result.err(
                ErrorCode.PERSISTENCE,
                "Поиск недоступен",
                {"error": str(exc)},
            )

        return Result.ok(result)
