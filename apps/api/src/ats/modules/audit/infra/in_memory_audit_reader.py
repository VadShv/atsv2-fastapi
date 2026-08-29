"""In-memory реализация AuditReader (JUGO-033).

Для dev/stub-режима. Хранит записи в списке, фильтрует в Python.
"""

from __future__ import annotations

from ats.modules.audit.domain.audit import AuditEntry
from ats.modules.audit.ports.audit_reader import AuditQuery, AuditReader


class InMemoryAuditReader(AuditReader):
    """In-memory реализация AuditReader."""

    def __init__(self, entries: list[AuditEntry] | None = None) -> None:
        self._entries: list[AuditEntry] = entries or []

    def add(self, entry: AuditEntry) -> None:
        """Добавить запись (для тестов)."""
        self._entries.append(entry)

    async def query(self, query: AuditQuery) -> list[AuditEntry]:
        """Фильтровать записи по параметрам запроса."""
        results = [
            e for e in self._entries
            if e.tenant_id == query.tenant_id
            and (query.actor_id is None or e.actor_id == query.actor_id)
            and (query.action is None or e.action == query.action)
            and (query.entity_type is None or e.entity_type == query.entity_type)
            and (query.entity_id is None or e.entity_id == query.entity_id)
            and (query.trace_id is None or e.trace_id == query.trace_id)
            and (query.date_from is None or e.created_at >= query.date_from)
            and (query.date_to is None or e.created_at <= query.date_to)
        ]
        # Сортировка: newest first
        results.sort(key=lambda e: e.created_at, reverse=True)
        # Пагинация
        offset = max(0, query.offset)
        limit = min(max(1, query.limit), 1000)
        return results[offset : offset + limit]

    async def count(self, query: AuditQuery) -> int:
        """Посчитать количество записей по фильтрам."""
        results = await self.query(query)
        return len(results)
