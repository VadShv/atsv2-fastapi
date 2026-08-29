"""Outbox publisher: запись доменных событий в outbox в той же транзакции.

Контракт §4.3: каждое доменное изменение пишет событие в outbox_events в той же
транзакции. Outbox-relay затем публикует в Redis Streams (at-least-once).

Репозиторий вызывает publish_events() после сохранения агрегата, передавая
текущую сессию — событие попадает в ту же транзакцию (атомарность).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ats.infra.db.models.events import OutboxMessageORM
from ats.shared.events import ActorRef, DomainEvent, EventEnvelope

logger = logging.getLogger(__name__)


async def publish_events(
    session: AsyncSession,
    events: list[DomainEvent],
    actor: ActorRef | None = None,
) -> int:
    """Записать доменные события в outbox в текущей транзакции.

    Args:
        session: активная async-сессия (транзакция агрегата).
        events: события, собранные из агрегата (collect_events).
        actor: кто инициировал изменение (для конверта).

    Returns:
        Количество записанных событий.
    """
    count = 0
    for event in events:
        envelope = EventEnvelope.from_event(event, actor=actor)
        session.add(
            OutboxMessageORM(
                id=envelope.event_id,
                tenant_id=envelope.tenant_id,
                event_type=envelope.event_type,
                schema_version=envelope.schema_version,
                aggregate_type=envelope.aggregate.type,
                aggregate_id=envelope.aggregate.id,
                actor_type=envelope.actor.type.value,
                actor_id=envelope.actor.id,
                occurred_at=envelope.occurred_at,
                payload=envelope.to_dict(),
                attempts=0,
                last_error="",
                processed_at=None,
            )
        )
        count += 1
        logger.debug(
            "Enqueued outbox event %s (aggregate=%s:%s)",
            envelope.event_type,
            envelope.aggregate.type,
            envelope.aggregate.id,
        )
    return count
