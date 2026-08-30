"""In-memory реализации портов для dev/тестов и первичного запуска.

Позволяют запустить ядро без Postgres/Redis/LLM. В prod заменяются на реальные адаптеры.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from ats.infra.ai.stub_outputs import STUB_OUTPUTS, stub_embed
from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.domain.models import (
    AIChunk,
    AIRequest,
    AIResponse,
    AIUsage,
    ProvenanceRecord,
    StructuredResponse,
)
from ats.modules.ai_core.ports.provenance import ProvenanceLedger
from ats.modules.recruitment.domain.vacancy import Vacancy
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.shared.ids import ProvenanceId, TenantId, VacancyId

T = TypeVar("T", bound=BaseModel)


class InMemoryVacancyRepository(VacancyRepository):
    """In-memory репозиторий вакансий. Не персистентный — только для dev."""

    def __init__(self) -> None:
        self._store: dict[str, Vacancy] = {}

    async def save(self, vacancy: Vacancy) -> VacancyId:
        key = f"{vacancy.tenant_id.value}:{vacancy.id.value}"
        self._store[key] = vacancy
        return vacancy.id

    async def get(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Vacancy | None:
        key = f"{tenant_id.value}:{vacancy_id.value}"
        return self._store.get(key)

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Vacancy]:
        items = [v for k, v in self._store.items() if k.startswith(f"{tenant_id.value}:")]
        return items[offset : offset + limit]

    async def delete(self, tenant_id: TenantId, vacancy_id: VacancyId) -> bool:
        key = f"{tenant_id.value}:{vacancy_id.value}"
        if key in self._store:
            del self._store[key]
            return True
        return False


class InMemoryProvenanceLedger(ProvenanceLedger):
    """In-memory provenance ledger. Append-only по контракту, но хранит в dict."""

    def __init__(self) -> None:
        self._store: dict[str, ProvenanceRecord] = {}

    async def append(self, record: ProvenanceRecord) -> ProvenanceId:
        self._store[str(record.provenance_id)] = record
        return record.provenance_id

    async def get(
        self, tenant_id: TenantId, provenance_id: ProvenanceId
    ) -> ProvenanceRecord | None:
        return self._store.get(str(provenance_id))

    async def mark_verified(self, tenant_id: TenantId, provenance_id: ProvenanceId) -> None:
        record = self._store.get(str(provenance_id))
        if record is not None:
            object.__setattr__(record, "human_verified", True)


class StubAIGateway(AIGateway):
    """Stub-реализация AIGateway для запуска без реальной LLM.

    Возвращает предзаготовленный structured output из STUB_OUTPUTS по prompt_id.
    Позволяет разрабатывать фронт и тестировать поток без затрат на LLM.
    """

    _DIMENSION = 1536

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    async def embed(self, tenant_id, text: str) -> list[float]:  # type: ignore[no-untyped-def]
        return stub_embed(text, self._DIMENSION)

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            provenance_id=ProvenanceId.generate(),
            content="[stub] AI response",
            raw_output="[stub] AI response",
            model="stub",
            usage=AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0),
            latency_ms=0,
        )

    async def stream(self, request: AIRequest):  # type: ignore[override]
        yield AIChunk(delta="[stub] ", provenance_id=ProvenanceId.generate())

    async def structured(self, request: AIRequest, schema: type[T]) -> StructuredResponse[T]:
        raw = _stub_for(request.prompt_id, schema)
        parsed = schema.model_validate_json(raw)
        return StructuredResponse(
            provenance_id=ProvenanceId.generate(),
            parsed=parsed,
            raw_output=raw,
            model="stub",
            usage=AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0),
            latency_ms=1,
            repaired=False,
        )


def _stub_for(prompt_id: str, schema: type[BaseModel]) -> str:
    """Диспетчер stub-выводов по prompt_id."""
    factory = STUB_OUTPUTS.get(prompt_id)
    if factory is not None:
        return factory()
    # Общий stub — минимальный валидный объект из example схемы
    return schema.model_json_schema().get("example", "{}")
