"""Встроенные задачи: outbox-relay и event-consumer как arq-функции.

Эти задачи связывают инфраструктуру событий (relay/consumer) с каркасом воркеров arq.
Запускаются воркером очереди `index` (relay) и `ai` (consumer events:ai) и т.д.

В stub-режиме (нет Redis / нет БД) они безопасно noop.
"""

from __future__ import annotations

import logging
from typing import Any

from ats.infra.workers.base_task import BaseTask, TaskContext
from ats.infra.workers.redis_client import get_redis

logger = logging.getLogger(__name__)


class OutboxRelayTask(BaseTask):
    """Цикл outbox-relay: читает outbox → публикует в Redis Streams.

    Запускается как long-running job в очереди `index`.
    Внутри вызывает OutboxRelay.relay_once() в цикле до shutdown.
    """

    name = "outbox_relay"

    async def execute(
        self, ctx: TaskContext, **params: Any
    ) -> dict[str, Any] | None:
        from ats.infra.events.relay import OutboxRelay
        from ats.infra.db.session import get_session_factory

        redis = ctx.redis or await get_redis()
        session_factory = get_session_factory()
        relay = OutboxRelay(
            session_factory=session_factory,
            redis_client=redis,
            batch_size=params.get("batch_size", 100),
            poll_interval=params.get("poll_interval", 1.0),
        )
        await relay.run()
        return {"task": "outbox_relay", "status": "stopped"}


class EventConsumerTask(BaseTask):
    """Цикл event-consumer: читает Redis Stream → вызывает хендлеры.

    Параметры: stream, group, consumer_name.
    Хендлеры регистрируются через container/событийную шину.
    """

    name = "event_consumer"

    async def execute(
        self, ctx: TaskContext, **params: Any
    ) -> dict[str, Any] | None:
        from ats.infra.events.consumer import ConsumerConfig, EventConsumer

        redis = ctx.redis or await get_redis()
        if redis is None:
            logger.warning("EventConsumerTask: no Redis, exiting")
            return {"task": "event_consumer", "status": "no_redis"}

        config = ConsumerConfig(
            stream=params.get("stream", "events:core"),
            group=params.get("group", "ats-workers"),
            consumer_name=params.get("consumer_name", "worker-1"),
            poll_interval=params.get("poll_interval", 1.0),
            read_count=params.get("read_count", 10),
        )
        consumer = EventConsumer(config=config, redis_client=redis)

        # Регистрация хендлеров (через container если доступен)
        await self._register_handlers(consumer, ctx)

        await consumer.run()
        return {"task": "event_consumer", "status": "stopped"}

    async def _register_handlers(self, consumer: Any, ctx: TaskContext) -> None:
        """Регистрация хендлеров событий.

        В текущей фазе — заглушка: хендлеры будут подключаться по мере
        реализации модулей (скрининг, парсинг резюме, индексация).
        """
        # TODO: подключить хендлеры из container при реализации эпиков
        logger.debug("EventConsumerTask: handler registration placeholder")
