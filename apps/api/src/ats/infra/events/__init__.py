"""Инфраструктура событий.

- InProcessEventBus: синхронная in-process доставка для немедленных реакций.
- outbox_publisher: запись в outbox в той же транзакции (§4.3).
- relay: outbox → Redis Streams (at-least-once), метрика лага.
- consumer: база консьюмера с дедупликацией (inbox), ретраями и DLQ.
"""

from ats.infra.events.bus import InProcessEventBus
from ats.infra.events.consumer import ConsumerConfig, EventConsumer
from ats.infra.events.outbox_publisher import publish_events
from ats.infra.events.relay import OutboxRelay, RelayStats, topic_for

__all__ = [
    "ConsumerConfig",
    "EventConsumer",
    "InProcessEventBus",
    "OutboxRelay",
    "RelayStats",
    "publish_events",
    "topic_for",
]
