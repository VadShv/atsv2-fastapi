"""In-memory реализация AuditLogger для stub/dev-режима и тестов."""

from __future__ import annotations

from ats.modules.audit.domain.audit import AuditEntry


class InMemoryAuditLogger:
    """Хранит записи аудита в памяти. Для dev и тестов."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
