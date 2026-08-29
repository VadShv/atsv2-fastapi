"""Postgres-реализация AuditLogger — запись в append-only audit_log.

Пишет в той же транзакции, что и доменное изменение (атомарность аудита).
ТЗ §15: append-only, неизменяемые записи.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ats.infra.db.models.events import AuditLogORM
from ats.modules.audit.domain.audit import AuditEntry
from ats.modules.audit.ports.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class PgAuditLogger:
    """Реализация AuditLogger на Postgres. Пишет в текущей транзакции."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditLogORM(
                id=entry.id,
                tenant_id=entry.tenant_id,
                actor_id=entry.actor_id,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                details=entry.details,
                ip_address=entry.ip_address,
                user_agent=entry.user_agent,
                trace_id=entry.trace_id,
            )
        )
        logger.debug(
            "Audit: %s on %s:%s by %s",
            entry.action,
            entry.entity_type,
            entry.entity_id,
            entry.actor_id or "system",
        )
