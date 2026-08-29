"""Postgres-реализация AuditReader (JUGO-033).

Читает из партиционированной таблицы audit_log.
SECURE FIRST: только SELECT, RLS обеспечивает изоляцию тенантов.
БЫСТРЕЙШИЙ ПОИСК: composite index (tenant_id, created_at) — быстрый tenant-scoped запрос.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ats.infra.db.models.events import AuditLogORM
from ats.modules.audit.domain.audit import AuditEntry
from ats.modules.audit.ports.audit_reader import AuditQuery, AuditReader

logger = logging.getLogger(__name__)


class PgAuditReader(AuditReader):
    """Реализация AuditReader на Postgres. Только чтение."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def query(self, query: AuditQuery) -> list[AuditEntry]:
        """Найти записи аудита по фильтрам."""
        stmt = select(AuditLogORM).where(AuditLogORM.tenant_id == query.tenant_id)

        if query.actor_id is not None:
            stmt = stmt.where(AuditLogORM.actor_id == query.actor_id)
        if query.action is not None:
            stmt = stmt.where(AuditLogORM.action == query.action)
        if query.entity_type is not None:
            stmt = stmt.where(AuditLogORM.entity_type == query.entity_type)
        if query.entity_id is not None:
            stmt = stmt.where(AuditLogORM.entity_id == query.entity_id)
        if query.trace_id is not None:
            stmt = stmt.where(AuditLogORM.trace_id == query.trace_id)
        if query.date_from is not None:
            stmt = stmt.where(AuditLogORM.created_at >= query.date_from)
        if query.date_to is not None:
            stmt = stmt.where(AuditLogORM.created_at <= query.date_to)

        # Сортировка: newest first (использует composite index)
        stmt = stmt.order_by(AuditLogORM.created_at.desc())

        # Пагинация
        offset = max(0, query.offset)
        limit = min(max(1, query.limit), 1000)
        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        return [self._to_domain(row) for row in rows]

    async def count(self, query: AuditQuery) -> int:
        """Посчитать количество записей по фильтрам."""
        stmt = (
            select(func.count())
            .select_from(AuditLogORM)
            .where(AuditLogORM.tenant_id == query.tenant_id)
        )

        if query.actor_id is not None:
            stmt = stmt.where(AuditLogORM.actor_id == query.actor_id)
        if query.action is not None:
            stmt = stmt.where(AuditLogORM.action == query.action)
        if query.entity_type is not None:
            stmt = stmt.where(AuditLogORM.entity_type == query.entity_type)
        if query.entity_id is not None:
            stmt = stmt.where(AuditLogORM.entity_id == query.entity_id)
        if query.trace_id is not None:
            stmt = stmt.where(AuditLogORM.trace_id == query.trace_id)
        if query.date_from is not None:
            stmt = stmt.where(AuditLogORM.created_at >= query.date_from)
        if query.date_to is not None:
            stmt = stmt.where(AuditLogORM.created_at <= query.date_to)

        result = await self._session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    def _to_domain(row: AuditLogORM) -> AuditEntry:
        """Конвертировать ORM в доменную модель."""
        return AuditEntry(
            id=row.id,
            tenant_id=row.tenant_id,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            details=row.details,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            trace_id=row.trace_id,
            created_at=row.created_at,
        )
