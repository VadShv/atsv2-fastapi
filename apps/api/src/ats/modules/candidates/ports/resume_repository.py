"""Порт: репозиторий версий резюме."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.candidates.domain.resume import ResumeSource, ResumeVersion
from ats.shared.ids import CandidateId, TenantId


@runtime_checkable
class ResumeRepository(Protocol):
    """Репозиторий версий резюме: источники + версии + дедупликация."""

    # --- Sources ---

    async def save_source(self, source: ResumeSource) -> UUID: ...

    async def get_source(self, tenant_id: TenantId, source_id: UUID) -> ResumeSource | None: ...

    # --- Versions ---

    async def save_version(self, version: ResumeVersion) -> UUID: ...

    async def get_version(self, tenant_id: TenantId, version_id: UUID) -> ResumeVersion | None: ...

    async def list_versions(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[ResumeVersion]: ...

    async def find_by_content_hash(
        self, tenant_id: TenantId, candidate_id: CandidateId, content_hash: str
    ) -> ResumeVersion | None: ...

    async def get_next_version_number(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> int: ...
