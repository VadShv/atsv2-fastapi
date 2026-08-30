"""Тесты E-33: Embeddings API.

Эмбеддинги, косинусная схожесть, индексация, метаданные.
Использует StubAIGateway (ATS_STUB_MODE=1) — без реальной LLM.
StubAIGateway._DIMENSION = 4000 (соответствие pgvector_index_dim).
"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.shared.ids import TenantId

client = TestClient(app)

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# GET /api/v1/embeddings/info — метаданные
# ---------------------------------------------------------------------------


class TestEmbeddingInfo:
    """Тесты метаданных эмбеддинг-модели."""

    def test_info_returns_metadata(self) -> None:
        resp = client.get("/api/v1/embeddings/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["embedding_model"] == "openai/text-embedding-3-large"
        assert data["embedding_dimension"] == 4096
        assert data["pgvector_index_dim"] == 4000
        assert data["embedding_max_tokens"] == 8000

    def test_info_gateway_dimension_matches_stub(self) -> None:
        resp = client.get("/api/v1/embeddings/info")
        data = resp.json()
        # StubAIGateway._DIMENSION = 4000
        assert data["gateway_dimension"] == 4000


# ---------------------------------------------------------------------------
# POST /api/v1/embeddings — получить эмбеддинг
# ---------------------------------------------------------------------------


class TestEmbedText:
    """Тесты получения эмбеддинга текста."""

    def test_embed_returns_vector(self) -> None:
        resp = client.post(
            "/api/v1/embeddings",
            json={"text": "Python developer with FastAPI experience"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dimension"] == 4000
        assert len(data["embedding"]) == 4000
        assert data["text_preview"]

    def test_embed_is_deterministic(self) -> None:
        """Одинаковый текст -> одинаковый эмбеддинг (детерминизм stub)."""
        text = "Senior Python Developer PostgreSQL"
        resp1 = client.post("/api/v1/embeddings", json={"text": text})
        resp2 = client.post("/api/v1/embeddings", json={"text": text})
        assert resp1.json()["embedding"] == resp2.json()["embedding"]

    def test_embed_different_texts_differ(self) -> None:
        """Разные тексты -> разные эмбеддинги."""
        resp1 = client.post("/api/v1/embeddings", json={"text": "Python developer"})
        resp2 = client.post("/api/v1/embeddings", json={"text": "Java developer"})
        assert resp1.json()["embedding"] != resp2.json()["embedding"]

    def test_embed_empty_text_rejected(self) -> None:
        resp = client.post("/api/v1/embeddings", json={"text": ""})
        assert resp.status_code == 422

    def test_embed_text_preview_truncated(self) -> None:
        long_text = "A" * 300
        resp = client.post("/api/v1/embeddings", json={"text": long_text})
        data = resp.json()
        assert len(data["text_preview"]) == 100

    def test_embed_vector_is_normalized(self) -> None:
        """Stub-эмбеддинги нормализованы (L2 norm ~ 1)."""
        resp = client.post(
            "/api/v1/embeddings",
            json={"text": "python fastapi postgresql docker"},
        )
        vec = resp.json()["embedding"]
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# POST /api/v1/embeddings/similarity — косинусная схожесть
# ---------------------------------------------------------------------------


class TestSimilarity:
    """Тесты косинусной схожести."""

    def test_identical_texts_similarity_is_one(self) -> None:
        text = "Python developer with FastAPI"
        resp = client.post("/api/v1/embeddings/similarity", json={"text_a": text, "text_b": text})
        assert resp.status_code == 200
        data = resp.json()
        assert abs(data["similarity"] - 1.0) < 1e-6

    def test_different_texts_similarity_less_than_one(self) -> None:
        resp = client.post(
            "/api/v1/embeddings/similarity",
            json={
                "text_a": "Python developer FastAPI PostgreSQL",
                "text_b": "Java developer Spring Hibernate",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["similarity"] < 1.0

    def test_shared_words_higher_similarity(self) -> None:
        """Тексты с общими словами имеют более высокую схожесть."""
        resp_shared = client.post(
            "/api/v1/embeddings/similarity",
            json={
                "text_a": "python developer fastapi",
                "text_b": "python developer postgresql",
            },
        )
        resp_diff = client.post(
            "/api/v1/embeddings/similarity",
            json={
                "text_a": "python developer fastapi",
                "text_b": "java manager spring",
            },
        )
        sim_shared = resp_shared.json()["similarity"]
        sim_diff = resp_diff.json()["similarity"]
        assert sim_shared > sim_diff

    def test_similarity_previews_returned(self) -> None:
        resp = client.post(
            "/api/v1/embeddings/similarity",
            json={"text_a": "Python developer", "text_b": "Java developer"},
        )
        data = resp.json()
        assert data["text_a_preview"] == "Python developer"
        assert data["text_b_preview"] == "Java developer"

    def test_similarity_empty_rejected(self) -> None:
        resp = client.post(
            "/api/v1/embeddings/similarity",
            json={"text_a": "", "text_b": "test"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/embeddings/index — индексация документа
# ---------------------------------------------------------------------------


class TestIndexDocument:
    """Тесты индексации документа в поисковый движок."""

    def test_index_returns_document_id(self) -> None:
        resp = client.post(
            "/api/v1/embeddings/index",
            json={
                "text": "Python developer with 5 years experience",
                "metadata": {"skills": ["Python", "FastAPI"], "source": "manual"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"]
        assert data["dimension"] == 4000
        assert data["text_preview"]

    def test_index_document_searchable(self) -> None:
        """Индексированный документ находится через поиск."""
        client.post(
            "/api/v1/embeddings/index",
            json={
                "text": "Python developer FastAPI PostgreSQL Docker",
                "metadata": {"skills": ["Python"], "headline": "Backend Dev"},
            },
        )
        resp = client.post(
            "/api/v1/search/candidates",
            json={"query": "python fastapi", "limit": 10},
        )
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert len(hits) > 0
        assert "python" in hits[0].get("snippet", "").lower()

    def test_index_with_empty_metadata(self) -> None:
        resp = client.post(
            "/api/v1/embeddings/index",
            json={"text": "Some candidate text"},
        )
        assert resp.status_code == 200
        assert resp.json()["document_id"]

    def test_index_empty_text_rejected(self) -> None:
        resp = client.post(
            "/api/v1/embeddings/index",
            json={"text": ""},
        )
        assert resp.status_code == 422

    def test_index_metadata_preserved_in_search(self) -> None:
        """Метаданные индексированного документа (skills/headline) сохраняются в поиске."""
        client.post(
            "/api/v1/embeddings/index",
            json={
                "text": "uniquekeyworddeveloper Python",
                "metadata": {"skills": ["Python"], "headline": "Senior Backend Dev"},
            },
        )
        resp = client.post(
            "/api/v1/search/candidates",
            json={"query": "uniquekeyworddeveloper", "limit": 5},
        )
        hits = resp.json()["hits"]
        assert len(hits) > 0
        first = hits[0]
        assert first.get("headline") == "Senior Backend Dev"
        assert "Python" in first.get("skills", [])


# ---------------------------------------------------------------------------
# Интеграция: StubAIGateway dimension consistency
# ---------------------------------------------------------------------------


class TestDimensionConsistency:
    """Тесты консистентности размерности между gateway и pgvector."""

    def test_stub_dimension_is_4000(self) -> None:
        """StubAIGateway.dimension = 4000 (pgvector_index_dim)."""
        container = get_container()
        assert container.ai_gateway.dimension == 4000

    def test_embed_dimension_matches_gateway_dimension(self) -> None:
        """Размерность эмбеддинга из API = gateway.dimension."""
        container = get_container()
        gateway_dim = container.ai_gateway.dimension

        resp = client.post("/api/v1/embeddings", json={"text": "test text"})
        assert resp.json()["dimension"] == gateway_dim
