"""Порт AuditReader — чтение записей из append-only журнала аудита (JUGO-033).

SECURE FIRST: только чтение (SELECT), никогда не UPDATE/DELETE.
Фильтры: tenant_id (обязательный, RLS), actor_id, action, entity, date range.

Домен и application-слой зависят от этого интерфейса для просмотра аудита.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.audit.domain.audit import AuditEntry


@dataclass
class AuditQuery:
    """Фильтры для чтения audit log.

    Attributes:
        tenant_id: тенант (обязательный — RLS изоляция).
        actor_id: фильтр по субъекту (опционально).
        action: фильтр по типу действия (опционально, напр. "vacancy.create").
        entity_type: фильтр по типу сущности (опционально).
        entity_id: фильтр по ID сущности (опционально).
        trace_id: фильтр по trace_id (опционально).
        date_from: начало периода (опционально).
        date_to: конец периода (опционально).
        limit: максимум записей (default 100, max 1000).
        offset: сдвиг для пагинации.
    """

    tenant_id: UUID
    actor_id: UUID | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    trace_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = 100
    offset: int = 0


@runtime_checkable
class AuditReader(Protocol):
    """Порт: чтение из журнала аудита (только SELECT)."""

    async def query(self, query: AuditQuery) -> list[AuditEntry]:
        """Найти записи аудита по фильтрам. Возвращает отсортированные по created_at DESC."""
        ...

    async def count(self, query: AuditQuery) -> int:
        """Посчитать количество записей по фильтрам (для пагинации)."""
        ...
