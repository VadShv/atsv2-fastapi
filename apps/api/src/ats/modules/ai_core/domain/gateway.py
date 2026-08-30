"""Порт AIGateway — единая точка входа ко всем LLM.

Домен зависит от этого интерфейса, а не от конкретного провайдера (гексагонал).
Реализация (LiteLLM) живёт в infra/ai и подставляется через DI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar, runtime_checkable

from ats.modules.ai_core.domain.models import (
    AIChunk,
    AIRequest,
    AIResponse,
    StructuredResponse,
)

T = TypeVar("T")


@runtime_checkable
class AIGateway(Protocol):
    """Порт: единый шлюз к LLM с провенансом, retry/fallback и бюджетами.

    Включает embed() для семантического поиска кандидатов.
    """

    async def complete(self, request: AIRequest) -> AIResponse:
        """Текстовый completion с записью провенанса."""
        ...

    async def stream(self, request: AIRequest) -> AsyncIterator[AIChunk]:
        """Стриминг ответа. Provenance_id известен с первого чанка."""
        ...

    async def structured(self, request: AIRequest, schema: type[T]) -> StructuredResponse[T]:
        """Structured output: JSON по схеме + слой ремонта (устойчивость/whitebox)."""
        ...

    async def embed(self, tenant_id, text: str) -> list[float]:  # type: ignore[no-untyped-def]
        """Векторное представление текста для семантического поиска."""
        ...

    @property
    def dimension(self) -> int:
        """Размерность вектора эмбеддинга."""
        ...
