"""In-memory реализации портов для dev/тестов и первичного запуска.

Позволяют запустить ядро без Postgres/Redis/LLM. В prod заменяются на реальные адаптеры.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    Если передан provenance_ledger, записи сохраняются (whitebox), как в LiteLLMGateway.
    """

    _DIMENSION = 1536

    def __init__(self, provenance_ledger: ProvenanceLedger | None = None) -> None:
        self._provenance = provenance_ledger

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    async def embed(self, tenant_id, text: str) -> list[float]:  # type: ignore[no-untyped-def]
        return stub_embed(text, self._DIMENSION)

    async def complete(self, request: AIRequest) -> AIResponse:
        prov_id = ProvenanceId.generate()
        usage = AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0)
        content = "[stub] AI response"
        if self._provenance is not None:
            await self._record(request, "stub", content, content, usage, 0, prov_id)
        return AIResponse(
            provenance_id=prov_id,
            content=content,
            raw_output=content,
            model="stub",
            usage=usage,
            latency_ms=0,
        )

    async def stream(self, request: AIRequest):  # type: ignore[override]
        yield AIChunk(delta="[stub] ", provenance_id=ProvenanceId.generate())

    async def structured(self, request: AIRequest, schema: type[T]) -> StructuredResponse[T]:
        raw = _stub_for(request.prompt_id, schema)
        parsed = schema.model_validate_json(raw)
        prov_id = ProvenanceId.generate()
        usage = AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0)
        if self._provenance is not None:
            await self._record(request, "stub", raw, parsed.model_dump_json(), usage, 1, prov_id)
        return StructuredResponse(
            provenance_id=prov_id,
            parsed=parsed,
            raw_output=raw,
            model="stub",
            usage=usage,
            latency_ms=1,
            repaired=False,
        )

    async def _record(
        self,
        request: AIRequest,
        model: str,
        raw_output: str,
        parsed_output: str,
        usage: AIUsage,
        latency_ms: int,
        provenance_id: ProvenanceId,
    ) -> None:
        """Записать provenance в ledger (если доступен)."""
        record = ProvenanceRecord(
            provenance_id=provenance_id,
            tenant_id=request.tenant_id,
            skill=request.skill,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            model=model,
            input_hash=request.input_refs.get("input_hash", ""),
            input_refs=request.input_refs,
            raw_output=raw_output,
            parsed_output=parsed_output,
            confidence=None,
            latency_ms=latency_ms,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_usd=usage.cost_usd,
            timestamp=datetime.now(UTC),
            human_verified=False,
            reasoning_trace="",
            non_ai=False,
        )
        await self._provenance.append(record)


def _stub_for(prompt_id: str, schema: type[BaseModel]) -> str:
    """Диспетчер stub-выводов по prompt_id."""
    factory = STUB_OUTPUTS.get(prompt_id)
    if factory is not None:
        return factory()
    # Общий stub — минимальный валидный объект из example схемы
    return schema.model_json_schema().get("example", "{}")
