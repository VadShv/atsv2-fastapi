"""Тесты поискового ядра: движок (BM25+vector hybrid), фильтры, фасеты, use case, API."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.infra.search.in_memory_search_engine import InMemorySearchEngine
from ats.main import app
from ats.modules.search.application.search_candidates import (
    SearchCandidatesInput,
)
from ats.modules.search.domain.models import (
    FilterOperator,
    SearchableDocument,
    SearchFilter,
    SearchQuery,
)
from ats.shared.ids import TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_container()


def _doc(
    doc_id: str,
    text: str,
    skills: list[str] | None = None,
    headline: str = "",
    source: str = "direct",
) -> SearchableDocument:
    return SearchableDocument(
        id=uuid.UUID(doc_id),
        tenant_id=TENANT.value,
        text=text,
        metadata={
            "skills": skills or [],
            "headline": headline,
            "source": source,
        },
    )


class TestBM25Search:
    """Тесты текстового поиска (BM25) без эмбеддингов."""

    @pytest.mark.asyncio
    async def test_bm25_finds_matching_document(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "Python FastAPI developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "Java Spring developer"))

        result = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="Python FastAPI", limit=10)
        )
        assert result.total == 2
        assert result.hits[0].document_id == uuid.UUID("11111111-0000-0000-0000-000000000001")
        assert result.hits[0].bm25_score > 0
        assert result.hits[0].score == result.hits[0].bm25_score  # vector_weight=0

    @pytest.mark.asyncio
    async def test_bm25_empty_query_returns_all_zero_scores(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "Python dev"))

        result = await engine.search(SearchQuery(tenant_id=TENANT.value, query="", limit=10))
        assert result.total == 1
        assert result.hits[0].score == 0.0

    @pytest.mark.asyncio
    async def test_bm25_ranking_by_relevance(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(
            _doc(
                "11111111-0000-0000-0000-000000000001",
                "Python Python Python Python developer",
            )
        )
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "Python developer"))

        result = await engine.search(SearchQuery(tenant_id=TENANT.value, query="Python", limit=10))
        assert result.hits[0].bm25_score >= result.hits[1].bm25_score


class TestHybridSearch:
    """Тесты гибридного поиска BM25 ⊕ vector."""

    @pytest.mark.asyncio
    async def test_hybrid_uses_embedding_when_present(self) -> None:
        engine = InMemorySearchEngine()
        doc = _doc("11111111-0000-0000-0000-000000000001", "бэкенд разработчик питон")
        doc.embedding = [1.0, 0.0, 0.0]
        await engine.index(doc)
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "дизайнер интерфейсов"))

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="программист",
                query_embedding=[1.0, 0.0, 0.0],
                bm25_weight=0.5,
                vector_weight=0.5,
                limit=10,
            )
        )
        assert result.hits[0].vector_score > 0
        assert result.hits[0].document_id == uuid.UUID("11111111-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_hybrid_score_is_weighted_sum(self) -> None:
        engine = InMemorySearchEngine()
        doc = _doc("11111111-0000-0000-0000-000000000001", "Python developer")
        doc.embedding = [1.0, 0.0]
        await engine.index(doc)

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="Python",
                query_embedding=[1.0, 0.0],
                bm25_weight=0.4,
                vector_weight=0.6,
                limit=10,
            )
        )
        hit = result.hits[0]
        expected = 0.4 * hit.bm25_score + 0.6 * hit.vector_score
        assert abs(hit.score - expected) < 1e-9


class TestFilters:
    """Тесты фасетной фильтрации по metadata."""

    @pytest.mark.asyncio
    async def test_filter_any_matches_any_value(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(
            _doc(
                "11111111-0000-0000-0000-000000000001",
                "developer",
                skills=["Python", "FastAPI"],
            )
        )
        await engine.index(
            _doc(
                "22222222-0000-0000-0000-000000000002",
                "developer",
                skills=["Java"],
            )
        )

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="developer",
                filters=[
                    SearchFilter(
                        field="skills",
                        values=["Python"],
                        operator=FilterOperator.ANY,
                    )
                ],
                limit=10,
            )
        )
        assert result.total == 1
        assert "Python" in result.hits[0].metadata["skills"]

    @pytest.mark.asyncio
    async def test_filter_gte_numeric(self) -> None:
        engine = InMemorySearchEngine()
        d1 = _doc("11111111-0000-0000-0000-000000000001", "senior dev")
        d1.metadata["years"] = 10
        d2 = _doc("22222222-0000-0000-0000-000000000002", "junior dev")
        d2.metadata["years"] = 1
        await engine.index(d1)
        await engine.index(d2)

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="dev",
                filters=[
                    SearchFilter(
                        field="years",
                        values=["5"],
                        operator=FilterOperator.GTE,
                    )
                ],
                limit=10,
            )
        )
        assert result.total == 1
        assert result.hits[0].metadata["years"] == 10


class TestFacets:
    """Тесты подсчёта фасетов."""

    @pytest.mark.asyncio
    async def test_facets_count_by_field(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(
            _doc(
                "11111111-0000-0000-0000-000000000001",
                "dev",
                skills=["Python"],
                source="referral",
            )
        )
        await engine.index(
            _doc(
                "22222222-0000-0000-0000-000000000002",
                "dev",
                skills=["Python", "Java"],
                source="referral",
            )
        )
        await engine.index(
            _doc(
                "33333333-0000-0000-0000-000000000003",
                "dev",
                skills=["Java"],
                source="direct",
            )
        )

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="dev",
                facet_fields=["skills", "source"],
                limit=10,
            )
        )
        facets_by_field = {f.field: f for f in result.facets}
        skills_counts = {v.value: v.count for v in facets_by_field["skills"].values}
        assert skills_counts["Python"] == 2
        assert skills_counts["Java"] == 2

        source_counts = {v.value: v.count for v in facets_by_field["source"].values}
        assert source_counts["referral"] == 2
        assert source_counts["direct"] == 1


class TestPagination:
    @pytest.mark.asyncio
    async def test_pagination_offset_limit(self) -> None:
        engine = InMemorySearchEngine()
        for i in range(5):
            await engine.index(
                _doc(
                    f"0000000{i}-0000-0000-0000-00000000000{i}",
                    f"developer number {i}",
                )
            )

        page1 = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="developer", limit=2, offset=0)
        )
        page2 = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="developer", limit=2, offset=2)
        )
        assert page1.total == 5
        assert len(page1.hits) == 2
        assert len(page2.hits) == 2
        page1_ids = {h.document_id for h in page1.hits}
        page2_ids = {h.document_id for h in page2.hits}
        assert not (page1_ids & page2_ids)


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_search_isolated_by_tenant(self) -> None:
        engine = InMemorySearchEngine()
        other_tenant = TenantId.from_string("99999999-0000-0000-0000-000000000009")
        await engine.index(
            SearchableDocument(
                id=uuid.UUID("11111111-0000-0000-0000-000000000001"),
                tenant_id=TENANT.value,
                text="Python developer",
                metadata={},
            )
        )
        await engine.index(
            SearchableDocument(
                id=uuid.UUID("22222222-0000-0000-0000-000000000002"),
                tenant_id=other_tenant.value,
                text="Python developer",
                metadata={},
            )
        )

        result = await engine.search(SearchQuery(tenant_id=TENANT.value, query="Python", limit=10))
        assert result.total == 1


class TestRemoveDocument:
    @pytest.mark.asyncio
    async def test_remove_deletes_from_index(self) -> None:
        engine = InMemorySearchEngine()
        doc_id = uuid.UUID("11111111-0000-0000-0000-000000000001")
        await engine.index(_doc(str(doc_id), "Python developer"))
        await engine.remove(TENANT.value, doc_id)

        result = await engine.search(SearchQuery(tenant_id=TENANT.value, query="Python", limit=10))
        assert result.total == 0


class TestSearchCandidatesUseCase:
    """Тесты use case поиска через контейнер (stub AI)."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self) -> None:
        from ats.infra.container_helpers import get_container

        container = get_container()
        await container.search_engine.index(
            _doc(
                "11111111-0000-0000-0000-000000000001",
                "Python FastAPI PostgreSQL developer",
                skills=["Python", "FastAPI"],
                headline="Middle Python Developer",
            )
        )

        result = await container.search_candidates.execute(
            TENANT, SearchCandidatesInput(query="Python developer")
        )
        assert not is_error(result)
        sr = result.value
        assert sr.total == 1
        assert sr.hits[0].document_id == uuid.UUID("11111111-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_error(self) -> None:
        from ats.infra.container_helpers import get_container

        container = get_container()
        result = await container.search_candidates.execute(
            TENANT, SearchCandidatesInput(query="   ")
        )
        assert is_error(result)
        assert result.error.code.value == "validation"


class TestSearchAPI:
    """Тесты HTTP-эндпоинта поиска (async, общий event loop)."""

    @pytest.mark.asyncio
    async def test_search_candidates_endpoint(self) -> None:
        from ats.infra.container_helpers import get_container

        container = get_container()
        await container.search_engine.index(
            _doc(
                "11111111-0000-0000-0000-000000000001",
                "Python FastAPI developer",
                skills=["Python"],
                headline="Middle Python Developer",
                source="database",
            )
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={
                    "query": "Python developer",
                    "facet_fields": ["skills", "source"],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["hits"][0]["headline"] == "Middle Python Developer"
        assert "Python" in data["hits"][0]["skills"]
        assert data["took_ms"] >= 0
        facet_fields = {f["field"] for f in data["facets"]}
        assert {"skills", "source"} <= facet_fields

    @pytest.mark.asyncio
    async def test_search_with_filters(self) -> None:
        from ats.infra.container_helpers import get_container

        container = get_container()
        await container.search_engine.index(
            _doc(
                "11111111-0000-0000-0000-000000000001",
                "developer",
                skills=["Python"],
            )
        )
        await container.search_engine.index(
            _doc(
                "22222222-0000-0000-0000-000000000002",
                "developer",
                skills=["Java"],
            )
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={
                    "query": "developer",
                    "filters": [{"field": "skills", "values": ["Python"], "operator": "any"}],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Python" in data["hits"][0]["skills"]

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_400(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/search/candidates", json={"query": "   "})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_search_skip_embedding_bm25_only(self) -> None:
        from ats.infra.container_helpers import get_container

        container = get_container()
        await container.search_engine.index(
            _doc("11111111-0000-0000-0000-000000000001", "Python developer")
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={"query": "Python", "skip_embedding": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["hits"][0]["bm25_score"] > 0
        assert data["hits"][0]["vector_score"] == 0.0


class TestEndToEndIndexingViaUpload:
    """Сквозной тест: загрузка резюме → индексация → поиск находит кандидата."""

    def test_upload_then_search_finds_candidate(self) -> None:
        resume_text = "Иванов Иван\nMiddle Python Developer\nPython, FastAPI, PostgreSQL, Docker"
        upload_resp = client.post(
            "/api/v1/candidates/upload-resume",
            files={"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")},
            params={"source": "database"},
        )
        assert upload_resp.status_code == 201

        search_resp = client.post(
            "/api/v1/search/candidates",
            json={"query": "Python FastAPI", "facet_fields": ["skills", "source"]},
        )
        assert search_resp.status_code == 200
        data = search_resp.json()
        assert data["total"] >= 1
        hit = data["hits"][0]
        assert "Python" in hit["skills"]
