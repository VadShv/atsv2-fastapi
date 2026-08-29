"""Базовый mixin для агрегатов.

Предоставляет методы работы с доменными событиями (_record, collect_events).
НЕ является dataclass и НЕ объявляет полей — каждый агрегат сам объявляет
tenant_id и _events (последним, с default_factory), чтобы соблюсти порядок полей
dataclass (non-default перед default).
"""

from __future__ import annotations

from typing import Any

from ats.shared.events import DomainEvent


class AggregateRoot:
    """Mixin: коллекционирование доменных событий для outbox."""

    _events: list[DomainEvent]

    def _record(self, event: DomainEvent) -> None:
        """Записать событие: положить в очередь на публикацию."""
        self._events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        """Забрать события для публикации. Вызывает репозиторий после сохранения."""
        events = list(self._events)
        self._events.clear()
        return events

    def to_payload(self) -> dict[str, Any]:
        """Сериализация для событий. Переопределяется в подклассах."""
        return {}
