"""In-memory репозитории для заявок и кандидатов (dev/тесты)."""

from __future__ import annotations

from uuid import UUID

from ats.modules.candidates.domain.candidate import Candidate
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.recruitment.domain.application import Application
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import CandidateId, TenantId, VacancyId


class InMemoryCandidateRepository(CandidateRepository):
    def __init__(self) -> None:
        self._store: dict[str, Candidate] = {}

    async def save(self, candidate: Candidate) -> CandidateId:
        key = f"{candidate.tenant_id.value}:{candidate.id.value}"
        self._store[key] = candidate
        return candidate.id

    async def get(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> Candidate | None:
        key = f"{tenant_id.value}:{candidate_id.value}"
        return self._store.get(key)

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Candidate]:
        items = [
            v for k, v in self._store.items() if k.startswith(f"{tenant_id.value}:")
        ]
        return items[offset : offset + limit]


class InMemoryApplicationRepository(ApplicationRepository):
    def __init__(self) -> None:
        self._store: dict[str, Application] = {}

    async def save(self, application: Application) -> UUID:
        key = f"{application.tenant_id.value}:{application.id}"
        self._store[key] = application
        return application.id

    async def get(self, tenant_id: TenantId, application_id: UUID) -> Application | None:
        key = f"{tenant_id.value}:{application_id}"
        return self._store.get(key)

    async def list_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: VacancyId
    ) -> list[Application]:
        prefix = f"{tenant_id.value}:"
        return [
            v
            for k, v in self._store.items()
            if k.startswith(prefix) and v.vacancy_id == vacancy_id
        ]

    async def find_by_candidate_and_vacancy(
        self, tenant_id: TenantId, candidate_id: CandidateId, vacancy_id: VacancyId
    ) -> Application | None:
        prefix = f"{tenant_id.value}:"
        for k, v in self._store.items():
            if k.startswith(prefix) and v.candidate_id == candidate_id and v.vacancy_id == vacancy_id:
                return v
        return None
