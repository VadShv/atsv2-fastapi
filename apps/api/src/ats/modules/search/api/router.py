"""API-слой search: HTTP-эндпоинт гибридного поиска кандидатов."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.search.application.search_candidates import SearchCandidatesInput
from ats.modules.search.domain.models import FilterOperator, SearchFilter
from ats.shared.ids import TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/search", tags=["search"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.message
        )

    sr = result.value
    return SearchResponse(
        hits=[_to_hit(h) for h in sr.hits],
        total=sr.total,
        facets=[
            FacetResponse(
                field=f.field,
                values=[
                    FacetValueResponse(value=v.value, count=v.count)
                    for v in f.values
                ],
            )
            for f in sr.facets
        ],
        took_ms=sr.took_ms,
        query=sr.query,
    )
