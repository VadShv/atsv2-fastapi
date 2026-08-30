"""In-memory репозиторий результатов скрининга для dev/тестов (JUGO-400)."""

from __future__ import annotations

from uuid import UUID

from ats.modules.m1_screening.domain.screening import ScreeningResult
from ats.modules.m1_screening.ports.screening_repository import (
    ScreeningResultRepository,
)
from ats.shared.ids import ApplicationId, TenantId


class InMemoryScreeningResultRepository(ScreeningResultRepository):
    """In-memory репозиторий результатов скрининга. Не персистентный — только dev."""

    def __init__(self) -> None:
        self._store: dict[str, ScreeningResult] = {}

    @staticmethod
    def _key(tenant_id: TenantId, screening_id: UUID) -> str:
        return f"{tenant_id.value}:{screening_id}"

    async def save(self, result: ScreeningResult) -> UUID:
        self._store[self._key(result.tenant_id, result.id.value)] = result
        return result.id.value

    async def get(self, tenant_id: TenantId, screening_id: UUID) -> ScreeningResult | None:
        return self._store.get(self._key(tenant_id, screening_id))

    async def get_by_application(
        self, tenant_id: TenantId, application_id: ApplicationId
    ) -> ScreeningResult | None:
        for result in self._store.values():
            if str(result.tenant_id.value) == str(tenant_id.value) and str(
                result.application_id.value
            ) == str(application_id.value):
                return result
        return None

    async def list_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[ScreeningResult]:
        items = [
            r
            for r in self._store.values()
            if str(r.tenant_id.value) == str(tenant_id.value)
            and str(r.vacancy_id.value) == str(vacancy_id)
        ]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return items[offset : offset + limit]

    async def list_stale(self, tenant_id: TenantId, vacancy_id: UUID) -> list[ScreeningResult]:
        return [
            r
            for r in self._store.values()
            if str(r.tenant_id.value) == str(tenant_id.value)
            and str(r.vacancy_id.value) == str(vacancy_id)
            and r.is_stale
        ]
