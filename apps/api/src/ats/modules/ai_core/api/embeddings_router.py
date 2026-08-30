"""API-слой ai_core: Embeddings — эмбеддинги, схожесть, индексация.

E-33: Embeddings API. Эмбеддинги 4096 обрезаются до 4000 (pgvector HNSW halfvec).
Через AIGateway.embed() — единый шлюз (Cloud.ru в prod, stub в dev/тестах).

Эндпоинты:
- GET  /embeddings/info      — метаданные: размерность, модель, лимиты
- POST /embeddings           — получить эмбеддинг текста
- POST /embeddings/similarity — косинусная схожесть двух текстов
- POST /embeddings/index     — индексировать документ в поисковый движок
"""

from __future__ import annotations

import math
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ats.infra.ai.settings import settings as ai_settings
from ats.infra.container_helpers import get_container
from ats.modules.search.domain.models import SearchableDocument
from ats.shared.ids import TenantId

router = APIRouter(prefix="/embeddings", tags=["embeddings"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------


class EmbeddingInfoResponse(BaseModel):
    """Метаданные эмбеддинг-модели и конфигурации pgvector."""

    embedding_model: str = Field(description="Модель эмбеддингов (провайдер/модель)")
    embedding_dimension: int = Field(description="Полная размерность модели (до обрезки)")
    pgvector_index_dim: int = Field(description="Размерность индекса pgvector (после обрезки)")
    gateway_dimension: int = Field(description="Фактическая размерность вектора от gateway")
    embedding_max_tokens: int = Field(description="Макс. длина текста для эмбеддинга (токены)")


class EmbedRequest(BaseModel):
    """Запрос на получение эмбеддинга текста."""

    text: str = Field(min_length=1, description="Текст для векторизации")


class EmbedResponse(BaseModel):
    """Эмбеддинг текста + метаданные."""

    text_preview: str = Field(description="Первые 100 символов исходного текста")
    dimension: int = Field(description="Размерность вектора")
    embedding: list[float] = Field(description="Вектор эмбеддинга")


class SimilarityRequest(BaseModel):
    """Запрос на косинусную схожесть двух текстов."""

    text_a: str = Field(min_length=1, description="Первый текст")
    text_b: str = Field(min_length=1, description="Второй текст")


class SimilarityResponse(BaseModel):
    """Косинусная схожесть двух текстов (0..1 диапазон может быть шире)."""

    text_a_preview: str
    text_b_preview: str
    similarity: float = Field(description="Косинусная схожесть [-1, 1]")


class IndexDocumentRequest(BaseModel):
    """Запрос на индексацию документа в поисковый движок."""

    text: str = Field(min_length=1, description="Текст документа для индексации")
    metadata: dict[str, object] = Field(
        default_factory=dict,
        description="Метаданные документа (навыки, источник, должность и т.д.)",
    )


class IndexDocumentResponse(BaseModel):
    """Результат индексации: document_id + dimension."""

    document_id: str
    dimension: int
    text_preview: str


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Косинусная схожесть двух векторов.

    Векторы могут быть разной длины — обрезаем до меньшего (SECURE FIRST).
    """
    min_len = min(len(vec_a), len(vec_b))
    if min_len == 0:
        return 0.0
    dot = sum(vec_a[i] * vec_b[i] for i in range(min_len))
    norm_a = math.sqrt(sum(v * v for v in vec_a[:min_len]))
    norm_b = math.sqrt(sum(v * v for v in vec_b[:min_len]))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _preview(text: str, length: int = 100) -> str:
    """Первые `length` символов текста (без переноса строк)."""
    cleaned = text.replace("\n", " ").strip()
    return cleaned[:length]


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@router.get(
    "/info",
    response_model=EmbeddingInfoResponse,
    summary="Метаданные эмбеддинг-модели и конфигурации pgvector",
)
async def get_embedding_info() -> EmbeddingInfoResponse:
    container = get_container()
    return EmbeddingInfoResponse(
        embedding_model=ai_settings.embedding_model,
        embedding_dimension=ai_settings.embedding_dimension,
        pgvector_index_dim=ai_settings.pgvector_index_dim,
        gateway_dimension=container.ai_gateway.dimension,
        embedding_max_tokens=ai_settings.embedding_max_tokens,
    )


@router.post(
    "",
    response_model=EmbedResponse,
    summary="Получить эмбеддинг текста",
)
async def embed_text(body: EmbedRequest) -> EmbedResponse:
    container = get_container()
    embedding = await container.ai_gateway.embed(_DEFAULT_TENANT, body.text)
    return EmbedResponse(
        text_preview=_preview(body.text),
        dimension=len(embedding),
        embedding=embedding,
    )


@router.post(
    "/similarity",
    response_model=SimilarityResponse,
    summary="Косинусная схожесть двух текстов",
)
async def compute_similarity(body: SimilarityRequest) -> SimilarityResponse:
    container = get_container()
    embedding_a = await container.ai_gateway.embed(_DEFAULT_TENANT, body.text_a)
    embedding_b = await container.ai_gateway.embed(_DEFAULT_TENANT, body.text_b)
    return SimilarityResponse(
        text_a_preview=_preview(body.text_a),
        text_b_preview=_preview(body.text_b),
        similarity=_cosine_similarity(embedding_a, embedding_b),
    )


@router.post(
    "/index",
    response_model=IndexDocumentResponse,
    summary="Индексировать документ в поисковый движок (админка/тесты)",
)
async def index_document(body: IndexDocumentRequest) -> IndexDocumentResponse:
    container = get_container()
    embedding = await container.ai_gateway.embed(_DEFAULT_TENANT, body.text)

    document = SearchableDocument(
        id=uuid4(),
        tenant_id=_DEFAULT_TENANT.value,
        text=body.text,
        embedding=embedding,
        metadata=body.metadata,
    )
    await container.search_engine.index(document)

    return IndexDocumentResponse(
        document_id=str(document.id),
        dimension=len(embedding),
        text_preview=_preview(body.text),
    )
