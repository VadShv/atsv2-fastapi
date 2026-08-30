"""In-memory реализации репозиториев вебхуков (JUGO-192).

Для dev-режима (ATS_STUB_MODE=1).
Prod → PostgreSQL (WebhookSubscriptionRepositoryPg, WebhookDeliveryRepositoryPg).
"""

from __future__ import annotations

from datetime import UTC, datetime

from ats.modules.webhooks.domain.webhook import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookSubscription,
)
from ats.modules.webhooks.ports.webhook_repository import (
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)
from ats.shared.ids import TenantId


class InMemoryWebhookSubscriptionRepository(WebhookSubscriptionRepository):
    """In-memory репозиторий подписок с tenant isolation."""

    def __init__(self) -> None:
        self._store: dict[str, WebhookSubscription] = {}

    async def save(self, subscription: WebhookSubscription) -> WebhookSubscription:
        self._store[str(subscription.id)] = subscription
        return subscription

    async def get_by_id(self, tenant: TenantId, subscription_id: str) -> WebhookSubscription | None:
        sub = self._store.get(subscription_id)
        if sub is None or sub.tenant_id != tenant.value:
            return None
        return sub

    async def list_all(self, tenant: TenantId) -> list[WebhookSubscription]:
        return [s for s in self._store.values() if s.tenant_id == tenant.value]

    async def find_by_event(self, tenant: TenantId, event_type: str) -> list[WebhookSubscription]:
        return [
            s
            for s in self._store.values()
            if s.tenant_id == tenant.value and s.is_deliverable() and s.matches_event(event_type)
        ]

    async def delete(self, tenant: TenantId, subscription_id: str) -> bool:
        sub = self._store.get(subscription_id)
        if sub is None or sub.tenant_id != tenant.value:
            return False
        del self._store[subscription_id]
        return True


class InMemoryWebhookDeliveryRepository(WebhookDeliveryRepository):
    """In-memory репозиторий журнала доставок."""

    def __init__(self) -> None:
        self._store: dict[str, WebhookDelivery] = {}

    async def save(self, delivery: WebhookDelivery) -> WebhookDelivery:
        self._store[str(delivery.id)] = delivery
        return delivery

    async def get_by_id(self, delivery_id: str) -> WebhookDelivery | None:
        return self._store.get(delivery_id)

    async def list_by_subscription(
        self, subscription_id: str, limit: int = 50
    ) -> list[WebhookDelivery]:
        deliveries = [d for d in self._store.values() if str(d.subscription_id) == subscription_id]
        deliveries.sort(key=lambda d: d.created_at, reverse=True)
        return deliveries[:limit]

    async def list_pending_retries(self, limit: int = 100) -> list[WebhookDelivery]:
        now = datetime.now(UTC)
        pending = [
            d
            for d in self._store.values()
            if d.status == DeliveryStatus.RETRY
            and d.next_retry_at is not None
            and d.next_retry_at <= now
        ]
        pending.sort(key=lambda d: d.next_retry_at or now)
        return pending[:limit]
