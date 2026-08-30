"""Порт: репозиторий заявок (Application)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.recruitment.domain.application import Application
from ats.shared.ids import CandidateId, TenantId, VacancyId


@runtime_checkable
class ApplicationRepository(Protocol):
    async def save(self, application: Application) -> UUID: ...

    async def get(self, tenant_id: TenantId, application_id: UUID) -> Application | None: ...

    async def list_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: VacancyId
    ) -> list[Application]: ...

    async def list_by_candidate(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[Application]:
        """Все заявки кандидата — для проверки повторных откликов (JUGO-142)."""
        ...

    async def find_by_candidate_and_vacancy(
        self, tenant_id: TenantId, candidate_id: CandidateId, vacancy_id: VacancyId
    ) -> Application | None: ...
