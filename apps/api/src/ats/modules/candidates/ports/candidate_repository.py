"""Порт: репозиторий кандидатов и связанных сущностей (факты, теги, blacklist)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.candidates.domain.candidate import Candidate
from ats.modules.candidates.domain.facts import CandidateFact
from ats.modules.candidates.domain.tags import BlacklistEntry, CandidateTag
from ats.shared.ids import CandidateId, TenantId


@runtime_checkable
class CandidateRepository(Protocol):
    """Репозиторий кандидатов (CRUD + факты + теги + blacklist)."""

    # --- Candidate CRUD ---

    async def save(self, candidate: Candidate) -> CandidateId: ...

    async def get(self, tenant_id: TenantId, candidate_id: CandidateId) -> Candidate | None: ...

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Candidate]: ...

    async def delete(self, tenant_id: TenantId, candidate_id: CandidateId) -> bool: ...

    # --- Facts ---

    async def add_fact(self, fact: CandidateFact) -> None: ...

    async def list_facts(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[CandidateFact]: ...

    async def delete_fact(
        self, tenant_id: TenantId, candidate_id: CandidateId, fact_id: str
    ) -> bool: ...

    # --- Tags ---

    async def add_tag(self, tag: CandidateTag) -> None: ...

    async def list_tags(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[CandidateTag]: ...

    async def remove_tag(
        self, tenant_id: TenantId, candidate_id: CandidateId, tag_id: str
    ) -> bool: ...

    # --- Blacklist ---

    async def add_to_blacklist(self, entry: BlacklistEntry) -> None: ...

    async def get_blacklist_entry(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> BlacklistEntry | None: ...

    async def remove_from_blacklist(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> bool: ...

    async def is_blacklisted(self, tenant_id: TenantId, candidate_id: CandidateId) -> bool: ...
