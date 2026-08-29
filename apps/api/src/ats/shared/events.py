"""Доменные события.

Базовый класс и шина событий. Модули общаются только через события (in-process bus).
События пишутся в outbox в той же транзакции, что и агрегат (устойчивость).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DomainEvent:
    """Базовый доменный event. Имена подклассов — PastTense (напр. VacancyCreated)."""

    event_id: UUID
    occurred_at: datetime
    tenant_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(cls, tenant_id: UUID, payload: dict[str, Any] | None = None) -> DomainEvent:
        return cls(
            event_id=uuid4(),
            occurred_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            payload=payload or {},
        )


class EventBus(Protocol):
    """Порт: шина событий. Реализация — in-process + outbox-диспетчер."""

    def publish(self, event: DomainEvent) -> None:
        """Синхронная публикация в in-process шину (для немедленных реакций)."""
        ...

    async def enqueue_outbox(self, event: DomainEvent) -> None:
        """Запись в outbox для надёжной асинхронной доставки (at-least-once)."""
        ...
