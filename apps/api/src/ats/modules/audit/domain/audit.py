"""Доменная модель аудита (SECURE FIRST, compliance).

AuditLog — append-only запись о действии субъекта над сущностью.
ТЗ §15: кто, что, когда, откуда (IP/UA), trace_id. Записи неизменяемы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class AuditEntry:
    """Неизменяемая запись аудита.

    Attributes:
        id: идентификатор записи.
        tenant_id: тенант (изоляция).
        actor_id: кто совершил действие (user_id). None для system.
        action: действие (напр. "vacancy.create", "candidate.contacts.read").
        entity_type: тип сущности (vacancy, candidate, application).
        entity_id: идентификатор сущности.
        details: детали (до/после, контекст) — jsonb.
        ip_address: IP субъекта (откуда).
        user_agent: UA субъекта.
        trace_id: корреляционный идентификатор запроса (observability).
        created_at: момент записи.
    """

    id: UUID
    tenant_id: UUID
    actor_id: UUID | None
    action: str
    entity_type: str
    entity_id: str
    details: dict[str, object] = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    trace_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_id: UUID | None = None,
        details: dict[str, object] | None = None,
        ip_address: str = "",
        user_agent: str = "",
        trace_id: str = "",
    ) -> AuditEntry:
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            trace_id=trace_id,
            created_at=datetime.now(timezone.utc),
        )
