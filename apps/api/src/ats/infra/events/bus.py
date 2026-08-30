"""In-process event bus: синхронная публикация для немедленных реакций.

Домен публикует события через шину: in-process хендлеры реагируют сразу,
а persistence-слой (репозиторий) дополнительно пишет в outbox в той же транзакции.
Это разделяет «быструю реакцию» и «надёжную доставку».

Дополнительно поддерживает async-очереди для SSE: клиенты подписываются через
``subscribe_queue()``, получают ``asyncio.Queue``, в которую шина складывает
конверты событий (включая event_id / event_type) для стриминга.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from ats.shared.events import DomainEvent, EventEnvelope

logger = logging.getLogger(__name__)

# Синхронный хендлер: принимает доменное событие.
EventHandler = Callable[[DomainEvent], Any]


class InProcessEventBus:
    """Простая in-process шина: подписки по типу события.

    Не хранит историю — только доставка «здесь и сейчас».
    Для надёжной асинхронной доставки события пишутся в outbox (отдельно).

    SSE-подписчики подключаются через ``subscribe_queue()`` — шина конвертирует
    доменное событие в конверт и кладёт в ``asyncio.Queue``.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queues: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Подписать хендлер на тип события (имя класса)."""
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Subscribed handler %s to %s", handler.__name__, event_type)

    def subscribe_queue(self, maxsize: int = 256) -> asyncio.Queue[dict[str, Any]]:
        """Создать async-очередь для доставки конвертов событий (для SSE).

        Возвращает очередь, в которую шина кладёт словарь-конверт при каждой
        публикации. SSE-эндпоинт читает из очереди. Очередь ограничена: при
        переполнении старые события дропаются (logged) — SSE не блокирует домен.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._queues.append(queue)
        logger.debug("Subscribed SSE queue (total=%d)", len(self._queues))
        return queue

    def unsubscribe_queue(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Отписать очередь (при disconnect SSE-клиента)."""
        with contextlib.suppress(ValueError):
            self._queues.remove(queue)
        logger.debug("Unsubscribed SSE queue (total=%d)", len(self._queues))

    def publish(self, event: DomainEvent) -> None:
        """Синхронно доставить событие всем подписчикам.

        Ошибка в одном хендлере не блокирует остальных (логируется).
        Конверт события также кладётся во все SSE-очереди (non-blocking).
        """
        event_type = type(event).__name__
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("Handler %s failed for event %s", handler.__name__, event_type)
        logger.debug("Published %s to %d handler(s)", event_type, len(handlers))

        # Доставка в SSE-очереди (если есть подписчики)
        if self._queues:
            self._dispatch_to_queues(event)

    def _dispatch_to_queues(self, event: DomainEvent) -> None:
        """Положить конверт события во все SSE-очереди (non-blocking)."""
        try:
            envelope = EventEnvelope.from_event(event)
        except Exception:
            logger.exception("Failed to build envelope for SSE: %s", type(event).__name__)
            return
        envelope_dict = envelope.to_dict()
        for queue in list(self._queues):
            try:
                queue.put_nowait(envelope_dict)
            except asyncio.QueueFull:
                # Очередь переполнена — дропаем, чтобы не блокировать домен.
                # SSE-клиент должен переподключиться с Last-Event-ID.
                logger.warning("SSE queue full, dropping event %s", envelope_dict.get("event_type"))

    def publish_envelope(self, envelope_dict: dict[str, Any]) -> None:
        """Положить готовый конверт-словарь во все SSE-очереди (non-blocking).

        Используется relay/consumer при доставке из Redis Streams, чтобы
        проксировать события в SSE без повторной сериализации доменного объекта.
        """
        for queue in list(self._queues):
            try:
                queue.put_nowait(envelope_dict)
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event %s", envelope_dict.get("event_type"))
