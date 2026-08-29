"""Порт: репозиторий кандидатов."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.candidates.domain.candidate import Candidate
from ats.shared.ids import CandidateId, TenantId


@runtime_checkable
class CandidateRepository(Protocol):
    async def save(self, candidate: Candidate) -> CandidateId: ...

    async def get(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> Candidate | None: ...

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Candidate]: ...
