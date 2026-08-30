"""Порт: поисковый движок (гексагонал).

Домен/application зависит от этого интерфейса, а не от конкретной реализации
(pgvector, in-memory). Реализация живёт в infra/search.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.search.domain.models import (
    SearchableDocument,
    SearchQuery,
    SearchResult,
)


@runtime_checkable
class SearchEngine(Protocol):
    """Порт: индексация и гибридный поиск документов.

    БЫСТРЕЙШИЙ ПОИСК: реализация обеспечивает BM25 ⊕ vector ⊕ фильтры → re-rank.
    """

    async def index(self, document: SearchableDocument) -> None:
        """Индексировать (или переиндексировать) документ."""
        ...

    async def remove(self, tenant_id, document_id) -> None:  # type: ignore[no-untyped-def]
        """Удалить документ из индекса."""
        ...

    async def search(self, query: SearchQuery) -> SearchResult:
        """Гибридный поиск с фильтрами, фасетами и re-ranking."""
        ...
