"""Порт AuditLogger — запись действий в append-only журнал (SECURE FIRST).

Домен и application-слой зависят от этого интерфейса. Реализация (Postgres) —
в infra. В stub-режиме — InMemoryAuditLogger.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.audit.domain.audit import AuditEntry


@runtime_checkable
class AuditLogger(Protocol):
    """Порт: запись в журнал аудита."""

    async def log(self, entry: AuditEntry) -> None:
        """Записать действие. Append-only: запись никогда не обновляется."""
        ...
