"""API-слой search: HTTP-эндпоинты гибридного поиска + CRUD синонимов.

JUGO-171: булев парсер запросов (ошибки возвращают 400 с подсказкой).
JUGO-172: CRUD синонимов для расширения запросов.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.search.application.search_candidates import SearchCandidatesInput
from ats.modules.search.domain.models import FilterOperator, SearchFilter
from ats.modules.search.domain.synonym import SynonymEntry
from ats.shared.ids import TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/search", tags=["search"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Поиск кандидатов
# ---------------------------------------------------------------------------


class FilterRequest(BaseModel):
    field: str
    values: list[str] = Field(default_factory=list)
    operator: str = "any"


class SearchRequest(BaseModel):
    query: str = Field(description="Поисковый запрос (текст)")
    filters: list[FilterRequest] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    facet_fields: list[str] = Field(
        default_factory=list,
        description="Поля metadata для фасетной фильтрации (напр. skills, source)",
    )
    bm25_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    skip_embedding: bool = Field(
        default=False, description="Только текстовый поиск (без эмбеддинга)"
    )


class HitResponse(BaseModel):
    document_id: UUID
    score: float
    bm25_score: float
    vector_score: float
    headline: str = ""
    skills: list[str] = Field(default_factory=list)
    snippet: str = ""


class FacetValueResponse(BaseModel):
    value: str
    count: int


class FacetResponse(BaseModel):
    field: str
    values: list[FacetValueResponse] = Field(default_factory=list)


class SearchResponse(BaseModel):
    hits: list[HitResponse]
    total: int
    facets: list[FacetResponse]
    took_ms: int
    query: str


def _to_hit(hit) -> HitResponse:
    meta = hit.metadata or {}
    return HitResponse(
        document_id=hit.document_id,
        score=hit.score,
        bm25_score=hit.bm25_score,
        vector_score=hit.vector_score,
        headline=meta.get("headline", ""),
        skills=meta.get("skills", []),
        snippet=hit.snippet,
    )


@router.post(
    "/candidates",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Гибридный поиск кандидатов (BM25 + vector + фильтры → re-rank)",
)
async def search_candidates(request: SearchRequest) -> SearchResponse:
    filters = [
        SearchFilter(
            field=f.field,
            values=f.values,
            operator=FilterOperator(f.operator),
        )
        for f in request.filters
    ]

    container = get_container()
    result = await container.search_candidates.execute(
        tenant_id=_DEFAULT_TENANT,
        input_dto=SearchCandidatesInput(
            query=request.query,
            filters=filters,
            limit=request.limit,
            offset=request.offset,
            facet_fields=request.facet_fields,
            bm25_weight=request.bm25_weight,
            vector_weight=request.vector_weight,
            skip_embedding=request.skip_embedding,
        ),
    )

    if is_error(result):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.message)

    sr = result.value
    return SearchResponse(
        hits=[_to_hit(h) for h in sr.hits],
        total=sr.total,
        facets=[
            FacetResponse(
                field=f.field,
                values=[FacetValueResponse(value=v.value, count=v.count) for v in f.values],
            )
            for f in sr.facets
        ],
        took_ms=sr.took_ms,
        query=sr.query,
    )


# ---------------------------------------------------------------------------
# CRUD синонимов (JUGO-172)
# ---------------------------------------------------------------------------


class SynonymCreateRequest(BaseModel):
    """Создание записи синонимов."""

    term: str = Field(min_length=1, max_length=255, description="Термин для расширения")
    synonyms: list[str] = Field(default_factory=list, description="Список синонимов термина")


class SynonymResponse(BaseModel):
    """Ответ с записью синонимов."""

    id: UUID
    term: str
    synonyms: list[str] = Field(default_factory=list)


def _to_synonym_response(entry: SynonymEntry) -> SynonymResponse:
    return SynonymResponse(
        id=entry.id,
        term=entry.term,
        synonyms=entry.synonyms,
    )


@router.get(
    "/synonyms",
    response_model=list[SynonymResponse],
    status_code=status.HTTP_200_OK,
    summary="Получить все синонимы тенанта",
)
async def list_synonyms() -> list[SynonymResponse]:
    container = get_container()
    entries = await container.synonym_repository.list_all(_DEFAULT_TENANT)
    return [_to_synonym_response(e) for e in entries]


@router.post(
    "/synonyms",
    response_model=SynonymResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать или обновить запись синонимов (upsert по term)",
)
async def create_synonym(request: SynonymCreateRequest) -> SynonymResponse:
    container = get_container()
    entry = SynonymEntry(
        tenant_id=_DEFAULT_TENANT.value,
        term=request.term,
        synonyms=request.synonyms,
    )
    saved = await container.synonym_repository.save(entry)
    return _to_synonym_response(saved)


@router.get(
    "/synonyms/{entry_id}",
    response_model=SynonymResponse,
    status_code=status.HTTP_200_OK,
    summary="Получить запись синонимов по ID",
)
async def get_synonym(entry_id: str) -> SynonymResponse:
    container = get_container()
    entry = await container.synonym_repository.get(_DEFAULT_TENANT, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись синонимов не найдена",
        )
    return _to_synonym_response(entry)


@router.delete(
    "/synonyms/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить запись синонимов",
)
async def delete_synonym(entry_id: str) -> None:
    container = get_container()
    deleted = await container.synonym_repository.delete(_DEFAULT_TENANT, entry_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись синонимов не найдена",
        )
