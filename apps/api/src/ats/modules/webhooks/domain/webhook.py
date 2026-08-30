"""Доменная модель вебхуков (JUGO-192).

Контракт ТЗ §14.4:
    Подписка: {url, events[], secret}
    Подпись: X-Jugo-Signature: sha256=HMAC(body, secret)
    Таймштамп: защита от replay
    Ретраи: 1м/5м/30м/2ч/6ч
    degraded после исчерпания

SECURE FIRST: secret хранится только при создании (не возвращается в API).
WHITEBOX AI: журнал доставок с телом и статусом — прозрачность для аудита.
УСТОЙЧИВОСТЬ: exponential backoff ретраи, degraded-флаг для подписок.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class WebhookStatus(StrEnum):
    """Состояние подписки."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class DeliveryStatus(StrEnum):
    """Статус доставки вебхука."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRY = "retry"


# Ретраи по ТЗ: 1м/5м/30м/2ч/6ч
RETRY_DELAYS_SECONDS = [60, 300, 1800, 7200, 21600]
MAX_RETRIES = len(RETRY_DELAYS_SECONDS)

# Таймштамп tolerance: 5 минут против replay
TIMESTAMP_TOLERANCE_SECONDS = 300


@dataclass(frozen=True)
class WebhookSubscription:
    """Подписка на события: URL + список событий + секрет.

    SECURE FIRST: secret генерируется сервером, показывается один раз.
    """

    id: UUID
    tenant_id: UUID
    url: str
    events: list[str]
    secret: str
    status: WebhookStatus = WebhookStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def matches_event(self, event_type: str) -> bool:
        """Проверить, подписана ли подписка на тип события.

        Поддержка wildcard: events=['*'] -> все события.
        """
        if "*" in self.events:
            return True
        return event_type in self.events

    def is_deliverable(self) -> bool:
        """Можно ли доставлять вебхук (active или degraded)."""
        return self.status in (WebhookStatus.ACTIVE, WebhookStatus.DEGRADED)

    def mark_degraded(self) -> WebhookSubscription:
        """Пометить подписку как degraded (после исчерпания ретраев)."""
        return WebhookSubscription(
            id=self.id,
            tenant_id=self.tenant_id,
            url=self.url,
            events=self.events,
            secret=self.secret,
            status=WebhookStatus.DEGRADED,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def disable(self) -> WebhookSubscription:
        """Полностью отключить подписку."""
        return WebhookSubscription(
            id=self.id,
            tenant_id=self.tenant_id,
            url=self.url,
            events=self.events,
            secret=self.secret,
            status=WebhookStatus.DISABLED,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        url: str,
        events: list[str],
        secret: str | None = None,
    ) -> WebhookSubscription:
        """Создать новую подписку. Secret генерируется, если не передан."""
        if not url.startswith(("http://", "https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        if not events:
            raise ValueError("At least one event must be specified")
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            url=url,
            events=list(events),
            secret=secret or secrets.token_urlsafe(32),
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Сериализация без secret (для API-ответов).

        SECURE FIRST: secret никогда не возвращается в ответах.
        """
        return {
            "id": str(self.id),
            "url": self.url,
            "events": self.events,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def sign_payload(body: bytes, secret: str) -> str:
    """Подписать тело запроса HMAC-SHA256.

    Возвращает строку вида 'sha256=<hex>'.
    """
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Проверить подпись HMAC-SHA256 (использует hmac.compare_digest)."""
    expected = sign_payload(body, secret)
    return hmac.compare_digest(expected, signature_header)


def build_signature_header(body: bytes, secret: str, timestamp: datetime | None = None) -> str:
    """Построить заголовок подписи с таймштампом.

    Формат: t=<unix_ts>,sha256=<hex>
    """
    ts = int((timestamp or datetime.now(UTC)).timestamp())
    ts_body = f"{ts}.".encode() + body
    signature = hmac.new(secret.encode(), ts_body, hashlib.sha256).hexdigest()
    return f"t={ts},sha256={signature}"


def verify_signed_header(body: bytes, signed_header: str, secret: str) -> bool:
    """Проверить подпись с таймштампом (защита от replay).

    Формат заголовка: t=<unix_ts>,sha256=<hex>
    """
    try:
        parts = dict(p.split("=", 1) for p in signed_header.split(","))
        ts_str = parts.get("t", "")
        signature = parts.get("sha256", "")
        if not ts_str or not signature:
            return False

        ts = int(ts_str)
        now = int(datetime.now(UTC).timestamp())
        if abs(now - ts) > TIMESTAMP_TOLERANCE_SECONDS:
            return False

        ts_body = f"{ts}.".encode() + body
        expected = hmac.new(secret.encode(), ts_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except (ValueError, KeyError):
        return False


@dataclass(frozen=True)
class WebhookDelivery:
    """Журнал доставки одного вебхука (одна попытка).

    WHITEBOX AI: полное тело запроса/ответа + статус для аудита.
    """

    id: UUID
    subscription_id: UUID
    event_type: str
    payload: str  # JSON-строка тела запроса
    status: DeliveryStatus
    response_status: int | None = None
    response_body: str | None = None
    error: str | None = None
    attempt: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create_pending(
        cls, subscription_id: UUID, event_type: str, payload: str
    ) -> WebhookDelivery:
        return cls(
            id=uuid4(),
            subscription_id=subscription_id,
            event_type=event_type,
            payload=payload,
            status=DeliveryStatus.PENDING,
            attempt=0,
        )

    def mark_delivered(self, response_status: int, response_body: str) -> WebhookDelivery:
        return WebhookDelivery(
            id=self.id,
            subscription_id=self.subscription_id,
            event_type=self.event_type,
            payload=self.payload,
            status=DeliveryStatus.DELIVERED,
            response_status=response_status,
            response_body=response_body,
            attempt=self.attempt,
            created_at=self.created_at,
        )

    def mark_retry(self, error: str, response_status: int | None = None) -> WebhookDelivery:
        """Отметить попытку как требующую ретрая."""
        next_attempt = self.attempt + 1
        delay_idx = min(next_attempt - 1, MAX_RETRIES - 1)
        next_retry_at = datetime.now(UTC) + timedelta(seconds=RETRY_DELAYS_SECONDS[delay_idx])
        return WebhookDelivery(
            id=self.id,
            subscription_id=self.subscription_id,
            event_type=self.event_type,
            payload=self.payload,
            status=DeliveryStatus.RETRY,
            response_status=response_status,
            error=error,
            attempt=next_attempt,
            next_retry_at=next_retry_at,
            created_at=self.created_at,
        )

    def mark_failed(self, error: str, response_status: int | None = None) -> WebhookDelivery:
        return WebhookDelivery(
            id=self.id,
            subscription_id=self.subscription_id,
            event_type=self.event_type,
            payload=self.payload,
            status=DeliveryStatus.FAILED,
            response_status=response_status,
            error=error,
            attempt=self.attempt,
            created_at=self.created_at,
        )

    def is_terminal(self) -> bool:
        """Доставка завершена (успешно или с исчерпанием ретраев)."""
        return self.status in (DeliveryStatus.DELIVERED, DeliveryStatus.FAILED)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "subscription_id": str(self.subscription_id),
            "event_type": self.event_type,
            "status": self.status.value,
            "response_status": self.response_status,
            "error": self.error,
            "attempt": self.attempt,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "created_at": self.created_at.isoformat(),
        }
