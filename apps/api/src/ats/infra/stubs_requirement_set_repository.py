"""In-memory репозиторий наборов критериев для dev/тестов (JUGO-121)."""

from __future__ import annotations

from uuid import UUID

from ats.modules.recruitment.domain.requirement_set import (
    RequirementSet,
    RequirementSetStatus,
)
from ats.modules.recruitment.ports.requirement_set_repository import (
    RequirementSetRepository,
)
from ats.shared.ids import TenantId, VacancyId


class InMemoryRequirementSetRepository(RequirementSetRepository):
    """In-memory реализация RequirementSetRepository."""

    def __init__(self) -> None:
        self._store: dict[str, RequirementSet] = {}

    @staticmethod
    def _key(tenant_id: TenantId, set_id: UUID) -> str:
        return f"{tenant_id.value}:{set_id}"

    async def save(self, req_set: RequirementSet) -> UUID:
        self._store[self._key(req_set.tenant_id, req_set.id)] = req_set
        return req_set.id

    async def get(self, tenant_id: TenantId, set_id: UUID) -> RequirementSet | None:
        return self._store.get(self._key(tenant_id, set_id))

    async def list_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: VacancyId
    ) -> list[RequirementSet]:
        return [
            rs
            for rs in self._store.values()
            if str(rs.tenant_id.value) == str(tenant_id.value)
            and str(rs.vacancy_id.value) == str(vacancy_id.value)
        ]

    async def get_active(self, tenant_id: TenantId, vacancy_id: VacancyId) -> RequirementSet | None:
        for rs in self._store.values():
            if (
                str(rs.tenant_id.value) == str(tenant_id.value)
                and str(rs.vacancy_id.value) == str(vacancy_id.value)
                and rs.status == RequirementSetStatus.ACTIVE
            ):
                return rs
        return None

    async def get_next_version_number(self, tenant_id: TenantId, vacancy_id: VacancyId) -> int:
        versions = await self.list_by_vacancy(tenant_id, vacancy_id)
        if not versions:
            return 1
        return max(rs.version_number for rs in versions) + 1

    async def deactivate_active(self, tenant_id: TenantId, vacancy_id: VacancyId) -> None:
        active = await self.get_active(tenant_id, vacancy_id)
        if active is not None:
            active.archive()
