"""Домен поиска: запросы, результаты, фильтры, фасеты.

БЫСТРЕЙШИЙ ПОИСК: гибридный (BM25 ⊕ vector ⊕ фильтры → re-rank),
фасетная фильтрация, снippets, p95 < 100 мс.
Чистый домен, не зависит от инфраструктуры (pgvector и т.д.).
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class FilterOperator(str, Enum):
    """Оператор фильтра по полю metadata."""

    ANY = "any"
    ALL = "all"
    GTE = "gte"
    LTE = "lte"


class SearchFilter(BaseModel):
    """Фасетный фильтр по полю документа.

    ANY  — поле-список содержит любое из values (OR).
    ALL  — поле-список содержит все values (AND).
    GTE  — числовое поле >= values[0].
    LTE  — числовое поле <= values[0].
    """

    field: str
    values: list[str] = Field(default_factory=list)
    operator: FilterOperator = FilterOperator.ANY


class SearchableDocument(BaseModel):
    """Документ для индексации в поисковом движке.

    Соответствует кандидату: text — searchable_text из ParsedResume,
    metadata — навыки, источник, должность и т.д. для фильтрации/фасетов.
    """

    id: UUID
    tenant_id: UUID
    text: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchQuery(BaseModel):
    """Поисковый запрос: текст + эмбеддинг + фильтры + пагинация.

    Веса bm25_weight/vector_weight управляют балансом гибридного поиска.
    """

    tenant_id: UUID
    query: str
    query_embedding: list[float] | None = None
    filters: list[SearchFilter] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    bm25_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    # Поля, по которым считать фасеты (напр. ["skills", "source"])
    facet_fields: list[str] = Field(default_factory=list)


class FacetValue(BaseModel):
    value: str
    count: int


class Facet(BaseModel):
    field: str
    values: list[FacetValue] = Field(default_factory=list)


class SearchHit(BaseModel):
    """Одно попадание поиска с разложением баллов (whitebox)."""

    document_id: UUID
    score: float
    bm25_score: float
    vector_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    snippet: str = ""


class SearchResult(BaseModel):
    """Результат поиска: хиты + total + фасеты + метрики."""

    hits: list[SearchHit] = Field(default_factory=list)
    total: int = 0
    facets: list[Facet] = Field(default_factory=list)
    took_ms: int = 0
    query: str = ""
