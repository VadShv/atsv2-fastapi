"""AI Core — доменные модели запросов и ответов LLM.

Чистый домен, не зависит от провайдеров. Конкретный AIGateway реализуется в infra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Generic, TypeVar
from uuid import UUID, uuid4

from ats.shared.ids import ProvenanceId, TenantId

T = TypeVar("T")


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class AIRequest:
    """Запрос к LLM. Все вызовы идут через AIGateway — единая точка входа."""

    tenant_id: TenantId
    prompt_id: str
    prompt_version: str
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    # Идентификатор скилла/юзкейса, инициировавшего вызов (для метрик и бюджетов)
    skill: str = ""
    # Референсы на входные данные (для провенанса)
    input_refs: dict[str, str] = field(default_factory=dict)
    # Доп. переменные промпта (логируются в провенанс)
    variables: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIUsage:
    tokens_in: int
    tokens_out: int
    cost_usd: float


@dataclass(frozen=True)
class AIChunk:
    """Чанк стримингового ответа."""

    delta: str
    provenance_id: ProvenanceId


@dataclass(frozen=True)
class AIResponse:
    """Полный ответ LLM с провенансом."""

    provenance_id: ProvenanceId
    content: str
    model: str
    usage: AIUsage
    latency_ms: int
    # Сырой вывод (до парсинга) — для whitebox
    raw_output: str = ""
    # confidence модели (если провайдер поддерживает / оценён)
    confidence: float | None = None


@dataclass(frozen=True)
class StructuredResponse(Generic[T]):
    """Ответ с распарсенной структурой по схеме + провенанс."""

    provenance_id: ProvenanceId
    parsed: T
    raw_output: str
    model: str
    usage: AIUsage
    latency_ms: int
    confidence: float | None = None
    # True, если потребовался «ремонт» JSON (устойчивость/whitebox)
    repaired: bool = False


@dataclass(frozen=True)
class ProvenanceRecord:
    """Запись провенанса (whitebox AI). Хранится в provenance_ledger.

    Любой AI-артефакт ссылается на provenance_id, что позволяет объяснить решение.
    """

    provenance_id: ProvenanceId
    tenant_id: TenantId
    skill: str
    prompt_id: str
    prompt_version: str
    model: str
    input_hash: str
    input_refs: dict[str, str]
    raw_output: str
    parsed_output: str
    confidence: float | None
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    timestamp: datetime
    human_verified: bool = False
    reasoning_trace: str = ""
    # non_ai=True, если LLM был недоступен и использован детерминированный fallback
    non_ai: bool = False

    @classmethod
    def create(
        cls,
        *,
        tenant_id: TenantId,
        skill: str,
        prompt_id: str,
        prompt_version: str,
        model: str,
        input_hash: str,
        input_refs: dict[str, str],
        raw_output: str,
        parsed_output: str,
        confidence: float | None,
        latency_ms: int,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        non_ai: bool = False,
        reasoning_trace: str = "",
    ) -> ProvenanceRecord:
        return cls(
            provenance_id=ProvenanceId.generate(),
            tenant_id=tenant_id,
            skill=skill,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model=model,
            input_hash=input_hash,
            input_refs=input_refs,
            raw_output=raw_output,
            parsed_output=parsed_output,
            confidence=confidence,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            timestamp=datetime.now(timezone.utc),
            human_verified=False,
            reasoning_trace=reasoning_trace,
            non_ai=non_ai,
        )


# Локальный счётчик для генерации provenance_id в fallback-сценариях
def _new_provenance_id() -> UUID:
    return uuid4()
