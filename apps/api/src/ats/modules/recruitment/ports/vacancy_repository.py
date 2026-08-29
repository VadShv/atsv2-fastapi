"""Порт: репозиторий вакансий."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.recruitment.domain.vacancy import Vacancy
from ats.shared.ids import TenantId, VacancyId


@runtime_checkable
class VacancyRepository(Protocol):
    async def save(self, vacancy: Vacancy) -> VacancyId: ...

    async def get(
        self, tenant_id: TenantId, vacancy_id: VacancyId
    ) -> Vacancy | None: ...

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Vacancy]: ...
