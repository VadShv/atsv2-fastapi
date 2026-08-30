"""In-memory репозиторий дедупликации (JUGO-150..155, dev/тесты)."""

from __future__ import annotations

from uuid import UUID

from ats.modules.candidates.domain.dedup import ContactHash, MergeLog, MergeStatus
from ats.modules.candidates.ports.dedup_repository import DedupRepository
from ats.shared.ids import CandidateId, TenantId


class InMemoryDedupRepository(DedupRepository):
    """In-memory хранилище для дедупликации (contact hashes + merge_log)."""

    def __init__(self) -> None:
        self._contact_hashes: dict[str, ContactHash] = {}
        self._merge_logs: dict[tuple[UUID, UUID], MergeLog] = {}

    @staticmethod
    def _hkey(tenant_id: TenantId, candidate_id: UUID, kind: str, value_hash: str) -> str:
        return f"{tenant_id.value}:{candidate_id}:{kind}:{value_hash}"

    # --- Contact hashes ---

    async def add_contact_hash(self, contact: ContactHash) -> None:
        key = self._hkey(
            TenantId(contact.tenant_id),
            contact.candidate_id,
            contact.kind.value,
            contact.value_hash,
        )
        self._contact_hashes[key] = contact

    async def find_by_contact_hash(
        self, tenant_id: TenantId, kind: str, value_hash: str
    ) -> list[ContactHash]:
        results: list[ContactHash] = []
        for ch in self._contact_hashes.values():
            if (
                ch.tenant_id == tenant_id.value
                and ch.kind.value == kind
                and ch.value_hash == value_hash
            ):
                results.append(ch)
        return results

    async def list_contact_hashes(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> list[ContactHash]:
        return [
            ch
            for ch in self._contact_hashes.values()
            if ch.tenant_id == tenant_id.value and ch.candidate_id == candidate_id.value
        ]

    async def delete_contact_hashes(self, tenant_id: TenantId, candidate_id: CandidateId) -> int:
        to_remove = [
            k
            for k, ch in self._contact_hashes.items()
            if ch.tenant_id == tenant_id.value and ch.candidate_id == candidate_id.value
        ]
        for k in to_remove:
            self._contact_hashes.pop(k, None)
        return len(to_remove)

    async def transfer_contact_hashes(
        self,
        tenant_id: TenantId,
        from_candidate_id: CandidateId,
        to_candidate_id: CandidateId,
    ) -> int:
        """Перенести все хэши контактов с одного кандидата на другого.

        Пропускает дубликаты (если у survivor уже есть такой же контакт).
        """
        from_hashes = await self.list_contact_hashes(tenant_id, from_candidate_id)
        to_hashes = await self.list_contact_hashes(tenant_id, to_candidate_id)
        to_existing = {(ch.kind, ch.value_hash) for ch in to_hashes}

        transferred = 0
        for ch in from_hashes:
            if (ch.kind, ch.value_hash) in to_existing:
                continue
            new_hash = ContactHash(
                candidate_id=to_candidate_id.value,
                tenant_id=tenant_id.value,
                kind=ch.kind,
                value_hash=ch.value_hash,
                is_primary=ch.is_primary,
            )
            await self.add_contact_hash(new_hash)
            transferred += 1

        # Удаляем старые хэши
        await self.delete_contact_hashes(tenant_id, from_candidate_id)
        return transferred

    # --- Merge log ---

    async def save_merge_log(self, log: MergeLog) -> MergeLog:
        self._merge_logs[(log.tenant_id.value, log.id)] = log
        return log

    async def get_merge_log(self, tenant_id: TenantId, merge_log_id: str) -> MergeLog | None:
        return self._merge_logs.get((tenant_id.value, UUID(merge_log_id)))

    async def list_merge_logs(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId | None = None,
        include_rolled_back: bool = False,
    ) -> list[MergeLog]:
        logs = [
            log
            for (tid, _), log in self._merge_logs.items()
            if tid == tenant_id.value and (include_rolled_back or log.status == MergeStatus.MERGED)
        ]
        if candidate_id is not None:
            logs = [
                log
                for log in logs
                if log.survivor_id == candidate_id or log.absorbed_id == candidate_id
            ]
        return sorted(logs, key=lambda log: log.merged_at, reverse=True)

    async def find_active_merge_by_absorbed(
        self, tenant_id: TenantId, absorbed_id: CandidateId
    ) -> MergeLog | None:
        for log in self._merge_logs.values():
            if (
                log.tenant_id == tenant_id
                and log.absorbed_id == absorbed_id
                and log.status == MergeStatus.MERGED
            ):
                return log
        return None

    async def find_active_merge_by_survivor(
        self, tenant_id: TenantId, survivor_id: CandidateId
    ) -> list[MergeLog]:
        return [
            log
            for log in self._merge_logs.values()
            if (
                log.tenant_id == tenant_id
                and log.survivor_id == survivor_id
                and log.status == MergeStatus.MERGED
            )
        ]
