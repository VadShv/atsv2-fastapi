"""In-memory репозитории для заявок и кандидатов (dev/тесты).

Реализуют полный порт CandidateRepository: CRUD кандидатов + факты + теги + blacklist.
Не персистентные — только для dev и тестов (ATS_STUB_MODE=1).
"""

from __future__ import annotations

from uuid import UUID

from ats.modules.candidates.domain.candidate import Candidate
from ats.modules.candidates.domain.facts import CandidateFact, FactId
from ats.modules.candidates.domain.tags import BlacklistEntry, BlacklistReason, CandidateTag, TagId
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.recruitment.domain.application import Application
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import CandidateId, TenantId, UserId, VacancyId


class InMemoryCandidateRepository(CandidateRepository):
    """In-memory реализация полного порта CandidateRepository."""

    def __init__(self) -> None:
        self._candidates: dict[str, Candidate] = {}
        self._facts: dict[str, CandidateFact] = {}
        self._tags: dict[str, CandidateTag] = {}
        self._blacklist: dict[str, BlacklistEntry] = {}

    @staticmethod
    def _ckey(tenant_id: TenantId, candidate_id: CandidateId) -> str:
        return f"{tenant_id.value}:{candidate_id.value}"

    # --- Candidate CRUD ---

    async def save(self, candidate: Candidate) -> CandidateId:
        self._candidates[self._ckey(candidate.tenant_id, candidate.id)] = candidate
        return candidate.id

    async def get(self, tenant_id: TenantId, candidate_id: CandidateId) -> Candidate | None:
        return self._candidates.get(self._ckey(tenant_id, candidate_id))

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Candidate]:
        items = [v for k, v in self._candidates.items() if k.startswith(f"{tenant_id.value}:")]
        return items[offset : offset + limit]

    async def delete(self, tenant_id: TenantId, candidate_id: CandidateId) -> bool:
        key = self._ckey(tenant_id, candidate_id)
        existed = key in self._candidates
        self._candidates.pop(key, None)
        # Каскадно удаляем факты, теги, blacklist
        for store in (self._facts, self._tags, self._blacklist):
            to_remove = [
                k for k, v in store.items() if str(v.candidate_id.value) == str(candidate_id.value)
            ]
            for k in to_remove:
                store.pop(k, None)
        return existed

    # --- Facts ---

    async def add_fact(self, fact: CandidateFact) -> None:
        self._facts[str(fact.id.value)] = fact

    async def list_facts(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[CandidateFact]:
        return [
            f
            for f in self._facts.values()
            if str(f.candidate_id.value) == str(candidate_id.value)
            and str(f.tenant_id.value) == str(tenant_id.value)
        ]

    async def delete_fact(
        self, tenant_id: TenantId, candidate_id: CandidateId, fact_id: str
    ) -> bool:
        existed = fact_id in self._facts
        self._facts.pop(fact_id, None)
        return existed

    # --- Tags ---

    async def add_tag(self, tag: CandidateTag) -> None:
        self._tags[str(tag.id.value)] = tag

    async def list_tags(self, tenant_id: TenantId, candidate_id: CandidateId) -> list[CandidateTag]:
        return [
            t
            for t in self._tags.values()
            if str(t.candidate_id.value) == str(candidate_id.value)
            and str(t.tenant_id.value) == str(tenant_id.value)
        ]

    async def remove_tag(self, tenant_id: TenantId, candidate_id: CandidateId, tag_id: str) -> bool:
        existed = tag_id in self._tags
        self._tags.pop(tag_id, None)
        return existed

    # --- Blacklist ---

    async def add_to_blacklist(self, entry: BlacklistEntry) -> None:
        self._blacklist[self._ckey(entry.tenant_id, entry.candidate_id)] = entry

    async def get_blacklist_entry(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> BlacklistEntry | None:
        return self._blacklist.get(self._ckey(tenant_id, candidate_id))

    async def remove_from_blacklist(self, tenant_id: TenantId, candidate_id: CandidateId) -> bool:
        key = self._ckey(tenant_id, candidate_id)
        existed = key in self._blacklist
        self._blacklist.pop(key, None)
        return existed

    async def is_blacklisted(self, tenant_id: TenantId, candidate_id: CandidateId) -> bool:
        return self._ckey(tenant_id, candidate_id) in self._blacklist


# Re-export domain types used by callers that import from this module
__all__ = [
    "BlacklistEntry",
    "BlacklistReason",
    "CandidateFact",
    "CandidateTag",
    "FactId",
    "InMemoryApplicationRepository",
    "InMemoryCandidateRepository",
    "TagId",
    "UserId",
]


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
            v for k, v in self._store.items() if k.startswith(prefix) and v.vacancy_id == vacancy_id
        ]

    async def find_by_candidate_and_vacancy(
        self, tenant_id: TenantId, candidate_id: CandidateId, vacancy_id: VacancyId
    ) -> Application | None:
        prefix = f"{tenant_id.value}:"
        for k, v in self._store.items():
            if (
                k.startswith(prefix)
                and v.candidate_id == candidate_id
                and v.vacancy_id == vacancy_id
            ):
                return v
        return None
