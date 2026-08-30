"""Порты (интерфейсы) для вебхуков (JUGO-192).

Репозитории для подписок и журнала доставок.
In-memory реализации в infra/stubs_webhooks.py.
"""

from __future__ import annotations

from typing import Protocol

from ats.modules.webhooks.domain.webhook import WebhookDelivery, WebhookSubscription
from ats.shared.ids import TenantId


class WebhookSubscriptionRepository(Protocol):
    """Репозиторий подписок на вебхуки."""

    async def save(self, subscription: WebhookSubscription) -> WebhookSubscription:
        """Создать или обновить подписку."""
        ...

    async def get_by_id(self, tenant: TenantId, subscription_id: str) -> WebhookSubscription | None:
        """Получить подписку по ID."""
        ...

    async def list_all(self, tenant: TenantId) -> list[WebhookSubscription]:
        """Список всех подписок тенанта."""
        ...

    async def find_by_event(self, tenant: TenantId, event_type: str) -> list[WebhookSubscription]:
        """Найти подписки, ожидающие указанный тип события."""
        ...

    async def delete(self, tenant: TenantId, subscription_id: str) -> bool:
        """Удалить подписку. Возвращает True если удалена."""
        ...


class WebhookDeliveryRepository(Protocol):
    """Репозиторий журнала доставок вебхуков."""

    async def save(self, delivery: WebhookDelivery) -> WebhookDelivery:
        """Сохранить/обновить запись о доставке."""
        ...

    async def get_by_id(self, delivery_id: str) -> WebhookDelivery | None:
        """Получить запись по ID."""
        ...

    async def list_by_subscription(
        self, subscription_id: str, limit: int = 50
    ) -> list[WebhookDelivery]:
        """Список доставок для подписки (журнал)."""
        ...

    async def list_pending_retries(self, limit: int = 100) -> list[WebhookDelivery]:
        """Получить доставки, ожидающие ретрая (next_retry_at <= now)."""
        ...
