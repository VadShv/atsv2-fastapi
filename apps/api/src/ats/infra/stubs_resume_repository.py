"""In-memory репозиторий резюме для dev/тестов."""

from __future__ import annotations

from uuid import UUID

from ats.modules.candidates.domain.resume import ResumeSource, ResumeVersion
from ats.modules.candidates.ports.resume_repository import ResumeRepository
from ats.shared.ids import CandidateId, TenantId


class InMemoryResumeRepository(ResumeRepository):
    """In-memory реализация ResumeRepository."""

    def __init__(self) -> None:
        self._sources: dict[str, ResumeSource] = {}
        self._versions: dict[str, ResumeVersion] = {}

    @staticmethod
    def _skey(tenant_id: TenantId, source_id: UUID) -> str:
        return f"{tenant_id.value}:{source_id}"

    @staticmethod
    def _vkey(tenant_id: TenantId, version_id: UUID) -> str:
        return f"{tenant_id.value}:{version_id}"

    # --- Sources ---

    async def save_source(self, source: ResumeSource) -> UUID:
        self._sources[self._skey(source.tenant_id, source.id)] = source
        return source.id

    async def get_source(self, tenant_id: TenantId, source_id: UUID) -> ResumeSource | None:
        return self._sources.get(self._skey(tenant_id, source_id))

    # --- Versions ---

    async def save_version(self, version: ResumeVersion) -> UUID:
        self._versions[self._vkey(version.tenant_id, version.id)] = version
        return version.id

    async def get_version(self, tenant_id: TenantId, version_id: UUID) -> ResumeVersion | None:
        return self._versions.get(self._vkey(tenant_id, version_id))

    async def list_versions(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[ResumeVersion]:
        return [
            v
            for v in self._versions.values()
            if str(v.candidate_id.value) == str(candidate_id.value)
            and str(v.tenant_id.value) == str(tenant_id.value)
        ]

    async def find_by_content_hash(
        self, tenant_id: TenantId, candidate_id: CandidateId, content_hash: str
    ) -> ResumeVersion | None:
        for v in self._versions.values():
            if (
                str(v.candidate_id.value) == str(candidate_id.value)
                and str(v.tenant_id.value) == str(tenant_id.value)
                and v.content_hash == content_hash
            ):
                return v
        return None

    async def get_next_version_number(self, tenant_id: TenantId, candidate_id: CandidateId) -> int:
        versions = await self.list_versions(tenant_id, candidate_id)
        if not versions:
            return 1
        return max(v.version_number for v in versions) + 1
