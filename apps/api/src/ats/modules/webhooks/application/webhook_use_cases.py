"""Use cases для вебхуков (JUGO-192).

Управление подписками (CRUD) + диспетчер доставки.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx

from ats.modules.webhooks.domain.webhook import (
    MAX_RETRIES,
    WebhookDelivery,
    WebhookSubscription,
    build_signature_header,
)
from ats.modules.webhooks.ports.webhook_repository import (
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)
from ats.shared.events import DomainEvent, EventEnvelope, _resolve_event_type
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result, is_error

logger = logging.getLogger(__name__)


class WebhookManagementUseCase:
    """CRUD операций над подписками на вебхуки."""

    def __init__(
        self,
        subscription_repo: WebhookSubscriptionRepository,
        delivery_repo: WebhookDeliveryRepository,
    ) -> None:
        self._subs = subscription_repo
        self._deliveries = delivery_repo

    async def create_subscription(
        self,
        tenant: TenantId,
        url: str,
        events: list[str],
    ) -> Result[tuple[WebhookSubscription, str]]:
        """Создать подписку. Возвращает (subscription, secret) — secret показывается один раз."""
        try:
            sub = WebhookSubscription.create(tenant_id=tenant.value, url=url, events=events)
        except ValueError as e:
            return Result.err(ErrorCode.VALIDATION, str(e))

        saved = await self._subs.save(sub)
        return Result.ok((saved, sub.secret))

    async def get_subscription(
        self, tenant: TenantId, subscription_id: str
    ) -> Result[WebhookSubscription]:
        sub = await self._subs.get_by_id(tenant, subscription_id)
        if sub is None:
            return Result.err(ErrorCode.NOT_FOUND, "Subscription not found")
        return Result.ok(sub)

    async def list_subscriptions(self, tenant: TenantId) -> list[WebhookSubscription]:
        return await self._subs.list_all(tenant)

    async def delete_subscription(self, tenant: TenantId, subscription_id: str) -> Result[None]:
        deleted = await self._subs.delete(tenant, subscription_id)
        if not deleted:
            return Result.err(ErrorCode.NOT_FOUND, "Subscription not found")
        return Result.ok(None)

    async def test_subscription(
        self, tenant: TenantId, subscription_id: str
    ) -> Result[WebhookDelivery]:
        """Отправить тестовый вебхук (POST /webhooks/{id}/test).

        Создаёт synthetic event 'webhook.test' и доставляет его.
        """
        sub_result = await self.get_subscription(tenant, subscription_id)
        if is_error(sub_result):
            return sub_result

        sub = sub_result.value
        test_payload = json.dumps(
            {
                "event_type": "webhook.test",
                "event_id": str(UUID(int=0)),
                "occurred_at": datetime.now(UTC).isoformat(),
                "tenant_id": str(tenant.value),
                "payload": {"message": "This is a test webhook delivery."},
            }
        )

        delivery = WebhookDelivery.create_pending(
            subscription_id=sub.id, event_type="webhook.test", payload=test_payload
        )
        delivery = await self._deliver(sub, delivery)
        delivery = await self._deliveries.save(delivery)
        return Result.ok(delivery)

    async def list_deliveries(self, subscription_id: str, limit: int = 50) -> list[WebhookDelivery]:
        return await self._deliveries.list_by_subscription(subscription_id, limit)

    async def _deliver(
        self, sub: WebhookSubscription, delivery: WebhookDelivery
    ) -> WebhookDelivery:
        """Доставить вебхук через HTTP (одна попытка)."""
        body = delivery.payload.encode()
        signature = build_signature_header(body, sub.secret)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    sub.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Jugo-Signature": signature,
                        "X-Jugo-Event": delivery.event_type,
                    },
                )

            if response.status_code < 300:
                return delivery.mark_delivered(response.status_code, response.text[:1000])

            if delivery.attempt + 1 >= MAX_RETRIES:
                return delivery.mark_failed(f"HTTP {response.status_code}", response.status_code)

            return delivery.mark_retry(f"HTTP {response.status_code}", response.status_code)

        except Exception as e:
            if delivery.attempt + 1 >= MAX_RETRIES:
                return delivery.mark_failed(str(e))
            return delivery.mark_retry(str(e))


class WebhookDispatcher:
    """Диспетчер: принимает доменное событие → находит подписки → создаёт доставки.

    В dev-режиме доставка синхронная (для тестов).
    В prod — создания записи в очереди, воркер обрабатывает асинхронно.
    """

    def __init__(
        self,
        subscription_repo: WebhookSubscriptionRepository,
        delivery_repo: WebhookDeliveryRepository,
        management: WebhookManagementUseCase,
    ) -> None:
        self._subs = subscription_repo
        self._deliveries = delivery_repo
        self._management = management

    async def dispatch_event(self, event: DomainEvent) -> list[WebhookDelivery]:
        """Найти подписки для события и создать доставки.

        ТЗ §14.4: контакты кандидата не включаются в вебхук (безопасность).
        Получатель дочитывает по API в рамках своих скоупов.
        """
        event_type, _schema_version, _aggregate_type = _resolve_event_type(event)
        tenant = TenantId(event.tenant_id)

        subscriptions = await self._subs.find_by_event(tenant, event_type)
        if not subscriptions:
            return []

        envelope = EventEnvelope.from_event(event)
        payload = json.dumps(envelope.to_dict())

        deliveries: list[WebhookDelivery] = []
        for sub in subscriptions:
            delivery = WebhookDelivery.create_pending(
                subscription_id=sub.id, event_type=event_type, payload=payload
            )
            # Доставка (в dev — синхронная, в prod — через очередь)
            delivery = await self._management._deliver(sub, delivery)
            delivery = await self._deliveries.save(delivery)

            # Если доставка исчерпала ретраи → пометить подписку degraded
            if delivery.status.value == "failed":
                degraded = sub.mark_degraded()
                await self._subs.save(degraded)

            deliveries.append(delivery)

        return deliveries

    async def process_pending_retries(self) -> int:
        """Обработать ожидающие ретраи (вызывается воркером).

        Возвращает количество обработанных доставок.
        """
        pending = await self._deliveries.list_pending_retries(limit=100)
        count = 0

        for delivery in pending:
            sub = await self._subs.get_by_id(
                TenantId(delivery.subscription_id),
                str(delivery.subscription_id),
            )
            if sub is None:
                continue

            delivery = await self._management._deliver(sub, delivery)
            await self._deliveries.save(delivery)

            if delivery.status.value == "failed":
                degraded = sub.mark_degraded()
                await self._subs.save(degraded)

            count += 1

        return count
