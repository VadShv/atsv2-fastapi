"""База консьюмера: consumer groups + inbox/дедупликация + ретраи + DLQ.

Контракт §4.3 (E-16): потребители работают через consumer groups со своим inbox
(processed_events), поддерживают replay. At-least-once → хендлеры идемпотентны.

Паттерн:
  1. consumer.read(stream, group, consumer_name) → сообщения.
  2. Для каждого: проверить inbox (processed_events) — если обработано, ack.
  3. Выполнить хендлер (с ретраями). Успех → запись в inbox + ack. Провал после
     N попыток → DLQ (отдельный stream) + ack (чтобы не блокировать группу).
  4. replay(stream, group) — повторная обработка из inbox по фильтру.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Хендлер: принимает payload конверта. Должен быть идемпотентным.
EventHandler = Callable[[dict], Awaitable[None]]


@dataclass
class ConsumerConfig:
    """Конфигурация консьюмера."""

    stream: str
    group: str
    consumer_name: str
    poll_interval: float = 1.0
    read_count: int = 10
    max_retries: int = 3
    retry_base_delay: float = 0.5
    block_ms: int = 1000


@dataclass
class ConsumerStats:
    processed: int = 0
    failed: int = 0
    deduplicated: int = 0
    dlq: int = 0


class EventConsumer:
    """База консьюмера Redis Streams с дедупликацией и DLQ.

    Inbox (processed_events) хранится в Redis (SET по stream+group) — дедупликация
    at-least-once доставки. DLQ — отдельный stream `{stream}:dlq`.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        redis_client: object | None = None,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._handlers: dict[str, list[EventHandler]] = {}
        self._running = False
        self._inbox_key = f"inbox:{config.stream}:{config.group}"
        self._dlq_stream = f"{config.stream}:dlq"

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Подписать асинхронный хендлер на event_type."""
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Consumer subscribed %s → %s", event_type, handler.__name__)

    async def process_message(self, msg_id: str, fields: dict) -> ConsumerStats:
        """Обработать одно сообщение из стрима (видимая для тестов)."""
        stats = ConsumerStats()
        import json

        payload = json.loads(fields["data"]) if "data" in fields else fields
        event_id = payload.get("event_id", msg_id)
        event_type = payload.get("event_type", "")

        # Дедупликация
        if self._redis is not None and await self._seen(event_id):
            stats.deduplicated += 1
            if self._redis is not None:
                await self._redis.xack(self._config.stream, self._config.group, msg_id)
            return stats

        handlers = self._handlers.get(event_type, [])
        if not handlers:
            # Нет подписчиков — ack, чтобы не блокировать
            await self._ack(msg_id)
            return stats

        success = await self._run_handlers(handlers, payload)
        if success:
            await self._mark_seen(event_id)
            await self._ack(msg_id)
            stats.processed += 1
        else:
            stats.failed += 1
            await self._to_dlq(msg_id, payload)
            await self._ack(msg_id)
            stats.dlq += 1
        return stats

    async def _run_handlers(self, handlers: list[EventHandler], payload: dict) -> bool:
        """Выполнить хендлеры с ретраями. True если все успешны."""
        for handler in handlers:
            ok = False
            for attempt in range(1, self._config.max_retries + 1):
                try:
                    await handler(payload)
                    ok = True
                    break
                except Exception:
                    logger.exception(
                        "Handler %s failed (attempt %d/%d)",
                        handler.__name__,
                        attempt,
                        self._config.max_retries,
                    )
                    if attempt < self._config.max_retries:
                        await asyncio.sleep(self._config.retry_base_delay * (2 ** (attempt - 1)))
            if not ok:
                return False
        return True

    async def _seen(self, event_id: str) -> bool:
        if self._redis is None:
            return False
        return bool(await self._redis.sismember(self._inbox_key, event_id))

    async def _mark_seen(self, event_id: str) -> None:
        if self._redis is None:
            return
        await self._redis.sadd(self._inbox_key, event_id)

    async def _ack(self, msg_id: str) -> None:
        if self._redis is None:
            return
        await self._redis.xack(self._config.stream, self._config.group, msg_id)

    async def _to_dlq(self, msg_id: str, payload: dict) -> None:
        logger.error("Message %s → DLQ (%s)", msg_id, self._dlq_stream)
        if self._redis is None:
            return
        import json

        await self._redis.xadd(self._dlq_stream, {"data": json.dumps(payload, default=str)})

    async def run(self) -> None:
        """Бесконечный цикл чтения из consumer group. Для prod-воркера."""
        self._running = True
        if self._redis is None:
            logger.warning("Consumer %s: no Redis, not starting", self._config.consumer_name)
            return
        # Создать группу, если нет
        import contextlib

        with contextlib.suppress(Exception):  # группа уже существует
            await self._redis.xgroup_create(
                self._config.stream, self._config.group, id="0", mkstream=True
            )

        logger.info("Consumer %s started on %s", self._config.consumer_name, self._config.stream)
        while self._running:
            try:
                resp = await self._redis.xreadgroup(
                    self._config.group,
                    self._config.consumer_name,
                    {self._config.stream: ">"},
                    count=self._config.read_count,
                    block=self._config.block_ms,
                )
                if not resp:
                    continue
                for _stream, messages in resp:
                    for msg_id, fields in messages:
                        await self.process_message(msg_id, fields)
            except Exception:
                logger.exception("Consumer %s cycle crashed", self._config.consumer_name)
                await asyncio.sleep(self._config.poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("Consumer %s stopping", self._config.consumer_name)
