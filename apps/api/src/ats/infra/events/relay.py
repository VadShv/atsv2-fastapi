"""Outbox-relay: чтение outbox → Redis Streams (at-least-once).

Контракт §4.3: диспетчер читает outbox и публикует в Redis Streams
(events:core, events:ai, ...). Потребители работают через consumer groups.

Гарантия доставки — at-least-once: релей публикует в стрим, затем ставит
processed_at в той же БД-транзакции. Если падение между публикацией и коммитом —
событие доставится повторно (обработчики обязаны быть идемпотентными).

JUGO-161: метрики Prometheus — processed/failed/lag (ленивый импорт, no-op если
prometheus_client не установлен).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ats.infra.db.models.events import OutboxMessageORM
from ats.infra.metrics.registry import (
    outbox_failed_total,
    outbox_lag_seconds,
    outbox_published_total,
)
from ats.shared.events import _EVENT_TYPE_REGISTRY  # noqa: F401 - регистр топиков

logger = logging.getLogger(__name__)

# Топики по типу события. По умолчанию — events:core.
_TOPIC_BY_PREFIX = {
    "ai.": "events:ai",
}
DEFAULT_TOPIC = "events:core"


def topic_for(event_type: str) -> str:
    """Определить топик Redis Stream по event_type."""
    for prefix, topic in _TOPIC_BY_PREFIX.items():
        if event_type.startswith(prefix):
            return topic
    return DEFAULT_TOPIC


@dataclass
class RelayStats:
    """Метрики цикла релея."""

    processed: int = 0
    failed: int = 0
    lag_seconds: float = 0.0


class OutboxRelay:
    """Читает неотправленные события из outbox → публикует в Redis Streams.

    Работает как воркер: цикл с задержкой. В prod запускается отдельным процессом
    (arq worker / supervisord). В тестах — вызов relay_once().
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: object | None = None,
        batch_size: int = 100,
        poll_interval: float = 1.0,
        max_attempts: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._max_attempts = max_attempts
        self._running = False

    async def relay_once(self) -> RelayStats:
        """Один цикл: выбрать пачку неотправленных, опубликовать, отметить."""
        stats = RelayStats()
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OutboxMessageORM)
                        .where(OutboxMessageORM.processed_at.is_(None))
                        .order_by(OutboxMessageORM.created_at)
                        .limit(self._batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )

            if not rows:
                return stats

            now = datetime.now(UTC)
            for row in rows:
                topic = topic_for(row.event_type)
                try:
                    await self._publish_to_stream(topic, row.payload)
                    row.processed_at = now
                    stats.processed += 1
                except Exception as exc:
                    logger.exception("Failed to publish outbox %s (%s)", row.id, row.event_type)
                    row.attempts += 1
                    row.last_error = str(exc)[:500]
                    stats.failed += 1
                    if row.attempts >= self._max_attempts:
                        logger.error(
                            "Outbox message %s exceeded max_attempts → needs DLQ",
                            row.id,
                        )

            await session.commit()

            # Лаг: разница между now и самым старым обработанным
            if rows:
                oldest = min(r.occurred_at for r in rows)
                stats.lag_seconds = (now - oldest).total_seconds()

            # Метрики
            outbox_published_total.inc(stats.processed)
            outbox_failed_total.inc(stats.failed)
            outbox_lag_seconds.set(stats.lag_seconds)

            return stats

    async def _publish_to_stream(self, topic: str, payload: dict) -> None:
        """Публикация конверта в Redis Stream."""
        if self._redis is None:
            # Нет Redis (dev/stub) — просто логируем
            logger.debug("No Redis: would publish to %s: %s", topic, payload.get("event_type"))
            return
        await self._redis.xadd(topic, {"data": _to_json(payload)})

    async def run(self) -> None:
        """Бесконечный цикл релея. Для prod-воркера."""
        self._running = True
        logger.info(
            "Outbox relay started (batch=%d, interval=%.1fs)",
            self._batch_size,
            self._poll_interval,
        )
        while self._running:
            try:
                stats = await self.relay_once()
                if stats.processed or stats.failed:
                    logger.info(
                        "Relay cycle: processed=%d failed=%d lag=%.1fs",
                        stats.processed,
                        stats.failed,
                        stats.lag_seconds,
                    )
            except Exception:
                logger.exception("Relay cycle crashed")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("Outbox relay stopping")


def _to_json(payload: dict) -> str:
    import json

    return json.dumps(payload, default=str)
