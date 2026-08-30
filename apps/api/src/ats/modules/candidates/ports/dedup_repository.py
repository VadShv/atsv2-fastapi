"""Порт: репозиторий дедупликации (merge_log + contact hashes)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.candidates.domain.dedup import ContactHash, MergeLog
from ats.shared.ids import CandidateId, TenantId


@runtime_checkable
class DedupRepository(Protocol):
    """Репозиторий для дедупликации кандидатов."""

    # --- Contact hashes (JUGO-150) ---

    async def add_contact_hash(self, contact: ContactHash) -> None: ...

    async def find_by_contact_hash(
        self, tenant_id: TenantId, kind: str, value_hash: str
    ) -> list[ContactHash]: ...

    async def list_contact_hashes(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[ContactHash]: ...

    async def delete_contact_hashes(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> int: ...

    async def transfer_contact_hashes(
        self,
        tenant_id: TenantId,
        from_candidate_id: CandidateId,
        to_candidate_id: CandidateId,
    ) -> int: ...

    # --- Merge log (JUGO-152, JUGO-153) ---

    async def save_merge_log(self, log: MergeLog) -> MergeLog: ...

    async def get_merge_log(self, tenant_id: TenantId, merge_log_id: str) -> MergeLog | None: ...

    async def list_merge_logs(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId | None = None,
        include_rolled_back: bool = False,
    ) -> list[MergeLog]: ...

    async def find_active_merge_by_absorbed(
        self, tenant_id: TenantId, absorbed_id: CandidateId
    ) -> MergeLog | None: ...

    async def find_active_merge_by_survivor(
        self, tenant_id: TenantId, survivor_id: CandidateId
    ) -> list[MergeLog]: ...
