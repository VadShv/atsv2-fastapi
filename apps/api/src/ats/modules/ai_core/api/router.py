"""API-слой ai_core: статус LLM Gateway, список моделей, провенанс (whitebox AI).

E-30: единая точка наблюдаемости за AI-инфраструктурой.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.ai.settings import settings as ai_settings
from ats.infra.container_helpers import get_container
from ats.shared.ids import ProvenanceId, TenantId

router = APIRouter(prefix="/ai", tags=["ai"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------


class AIGatewayStatusResponse(BaseModel):
    """Статус LLM Gateway: провайдер, модели, размерность эмбеддингов."""

    provider: str = Field(description="Провайдер LLM (Cloud.ru / stub)")
    stub_mode: bool = Field(description="True — stub-режим без реальной LLM")
    default_model: str
    fallback_model: str | None = None
    embedding_model: str
    embedding_dimension: int
    pgvector_index_dim: int
    cache_enabled: bool
    max_retries: int
    timeout_seconds: float
    enable_non_ai_fallback: bool


class ModelInfoResponse(BaseModel):
    """Информация о доступной модели."""

    id: str
    role: str = Field(description="default / fallback / embedding")


class ModelsListResponse(BaseModel):
    """Список сконфигурированных моделей."""

    models: list[ModelInfoResponse]


class ProvenanceResponse(BaseModel):
    """Запись провенанса AI-вызова (whitebox)."""

    provenance_id: str
    tenant_id: str
    skill: str
    prompt_id: str
    prompt_version: str
    model: str
    input_hash: str
    input_refs: dict[str, str]
    raw_output: str
    parsed_output: str
    confidence: float | None = None
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    timestamp: str
    human_verified: bool = False
    reasoning_trace: str = ""
    non_ai: bool = False


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=AIGatewayStatusResponse,
    summary="Статус LLM Gateway (провайдер, модели, кэш)",
)
async def get_ai_status() -> AIGatewayStatusResponse:
    import os

    stub_mode = os.environ.get("ATS_STUB_MODE", "1") == "1"
    provider = "stub" if stub_mode else "cloudru"

    return AIGatewayStatusResponse(
        provider=provider,
        stub_mode=stub_mode,
        default_model=ai_settings.default_model,
        fallback_model=ai_settings.fallback_model,
        embedding_model=ai_settings.embedding_model,
        embedding_dimension=ai_settings.embedding_dimension,
        pgvector_index_dim=ai_settings.pgvector_index_dim,
        cache_enabled=ai_settings.cache_enabled,
        max_retries=ai_settings.max_retries,
        timeout_seconds=ai_settings.timeout_seconds,
        enable_non_ai_fallback=ai_settings.enable_non_ai_fallback,
    )


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="Список сконфигурированных моделей",
)
async def list_models() -> ModelsListResponse:
    models = [
        ModelInfoResponse(id=ai_settings.default_model, role="default"),
    ]
    if ai_settings.fallback_model:
        models.append(ModelInfoResponse(id=ai_settings.fallback_model, role="fallback"))
    models.append(ModelInfoResponse(id=ai_settings.embedding_model, role="embedding"))
    return ModelsListResponse(models=models)


@router.get(
    "/provenance/{provenance_id}",
    response_model=ProvenanceResponse,
    summary="Получить запись провенанса AI-вызова (whitebox)",
)
async def get_provenance(provenance_id: UUID) -> ProvenanceResponse:
    container = get_container()
    record = await container.provenance_ledger.get(_DEFAULT_TENANT, ProvenanceId(provenance_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provenance record not found",
        )
    return ProvenanceResponse(
        provenance_id=str(record.provenance_id.value),
        tenant_id=str(record.tenant_id.value),
        skill=record.skill,
        prompt_id=record.prompt_id,
        prompt_version=record.prompt_version,
        model=record.model,
        input_hash=record.input_hash,
        input_refs=record.input_refs,
        raw_output=record.raw_output,
        parsed_output=record.parsed_output,
        confidence=record.confidence,
        latency_ms=record.latency_ms,
        tokens_in=record.tokens_in,
        tokens_out=record.tokens_out,
        cost_usd=record.cost_usd,
        timestamp=record.timestamp.isoformat(),
        human_verified=record.human_verified,
        reasoning_trace=record.reasoning_trace,
        non_ai=record.non_ai,
    )


@router.post(
    "/provenance/{provenance_id}/verify",
    response_model=ProvenanceResponse,
    summary="Отметить AI-артефакт как проверенный человеком (human_verified)",
)
async def mark_provenance_verified(provenance_id: UUID) -> ProvenanceResponse:
    container = get_container()
    await container.provenance_ledger.mark_verified(_DEFAULT_TENANT, ProvenanceId(provenance_id))
    record = await container.provenance_ledger.get(_DEFAULT_TENANT, ProvenanceId(provenance_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provenance record not found",
        )
    return ProvenanceResponse(
        provenance_id=str(record.provenance_id.value),
        tenant_id=str(record.tenant_id.value),
        skill=record.skill,
        prompt_id=record.prompt_id,
        prompt_version=record.prompt_version,
        model=record.model,
        input_hash=record.input_hash,
        input_refs=record.input_refs,
        raw_output=record.raw_output,
        parsed_output=record.parsed_output,
        confidence=record.confidence,
        latency_ms=record.latency_ms,
        tokens_in=record.tokens_in,
        tokens_out=record.tokens_out,
        cost_usd=record.cost_usd,
        timestamp=record.timestamp.isoformat(),
        human_verified=record.human_verified,
        reasoning_trace=record.reasoning_trace,
        non_ai=record.non_ai,
    )
