"""In-memory репозиторий синонимов поиска (JUGO-172).

Для dev-режима и тестов (ATS_STUB_MODE=1).
Мульти-тенант: хранилище keyed по (tenant_id, term).
"""

from __future__ import annotations

from uuid import UUID

from ats.modules.search.domain.synonym import SynonymEntry
from ats.modules.search.ports.synonym_repository import SynonymRepository
from ats.shared.ids import TenantId


class InMemorySynonymRepository(SynonymRepository):
    """In-memory реализация репозитория синонимов."""

    def __init__(self) -> None:
        # key: (tenant_uuid, term_lower) → SynonymEntry
        self._entries: dict[tuple[UUID, str], SynonymEntry] = {}

    async def list_all(self, tenant_id: TenantId) -> list[SynonymEntry]:
        tid = tenant_id.value
        return [e for (t_uuid, _term), e in self._entries.items() if t_uuid == tid]

    async def get(self, tenant_id: TenantId, entry_id: str) -> SynonymEntry | None:
        try:
            eid = UUID(str(entry_id))
        except (ValueError, TypeError):
            return None
        for e in self._entries.values():
            if e.id == eid and e.tenant_id == tenant_id.value:
                return e
        return None

    async def find_by_term(self, tenant_id: TenantId, term: str) -> SynonymEntry | None:
        return self._entries.get((tenant_id.value, term.strip().lower()))

    async def save(self, entry: SynonymEntry) -> SynonymEntry:
        key = (entry.tenant_id, entry.term.lower())
        if key in self._entries:
            existing = self._entries[key]
            entry.id = existing.id
            entry.created_at = existing.created_at
        self._entries[key] = entry
        return entry

    async def delete(self, tenant_id: TenantId, entry_id: str) -> bool:
        try:
            eid = UUID(str(entry_id))
        except (ValueError, TypeError):
            return False
        for key, e in list(self._entries.items()):
            if e.id == eid and e.tenant_id == tenant_id.value:
                del self._entries[key]
                return True
        return False

    async def get_synonym_map(self, tenant_id: TenantId) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for (t_uuid, term_lower), e in self._entries.items():
            if t_uuid == tenant_id.value:
                result[term_lower] = [s.lower() for s in e.synonyms]
        return result
