"""In-process event bus: синхронная публикация для немедленных реакций.

Домен публикует события через шину: in-process хендлеры реагируют сразу,
а persistence-слой (репозиторий) дополнительно пишет в outbox в той же транзакции.
Это разделяет «быструю реакцию» и «надёжную доставку».
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ats.shared.events import DomainEvent

logger = logging.getLogger(__name__)

# Синхронный хендлер: принимает доменное событие.
EventHandler = Callable[[DomainEvent], Any]


class InProcessEventBus:
    """Простая in-process шина: подписки по типу события.

    Не хранит историю — только доставка «здесь и сейчас».
    Для надёжной асинхронной доставки события пишутся в outbox (отдельно).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Подписать хендлер на тип события (имя класса)."""
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Subscribed handler %s to %s", handler.__name__, event_type)

    def publish(self, event: DomainEvent) -> None:
        """Синхронно доставить событие всем подписчикам.

        Ошибка в одном хендлере не блокирует остальных (логируется).
        """
        event_type = type(event).__name__
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("Handler %s failed for event %s", handler.__name__, event_type)
        logger.debug("Published %s to %d handler(s)", event_type, len(handlers))
