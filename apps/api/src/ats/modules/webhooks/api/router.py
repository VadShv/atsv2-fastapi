"""API-слой вебхуков (JUGO-192).

Endpoints:
    GET    /webhooks                   — список подписок
    POST   /webhooks                   — создать подписку (возвращает secret один раз)
    GET    /webhooks/{id}              — детали подписки
    DELETE /webhooks/{id}              — удалить подписку
    POST   /webhooks/{id}/test         — отправить тестовый вебхук
    GET    /webhooks/{id}/deliveries   — журнал доставок
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.infra.middleware.problem_details import ProblemException
from ats.shared.ids import TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


class CreateSubscriptionRequest(BaseModel):
    url: str = Field(description="URL для доставки вебхуков (https://...)")
    events: list[str] = Field(
        description="Список типов событий (напр. ['application.created', '*'])"
    )


class SubscriptionResponse(BaseModel):
    id: UUID
    url: str
    events: list[str]
    status: str
    created_at: str
    updated_at: str


class CreateSubscriptionResponse(BaseModel):
    subscription: SubscriptionResponse
    secret: str = Field(
        description="Секрет для проверки подписи. Сохраните — показывается один раз."
    )


class DeliveryResponse(BaseModel):
    id: UUID
    subscription_id: UUID
    event_type: str
    status: str
    response_status: int | None = None
    error: str | None = None
    attempt: int
    next_retry_at: str | None = None
    created_at: str


class TestDeliveryResponse(BaseModel):
    delivery: DeliveryResponse


def _sub_to_response(sub) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        url=sub.url,
        events=sub.events,
        status=sub.status.value,
        created_at=sub.created_at.isoformat(),
        updated_at=sub.updated_at.isoformat(),
    )


def _delivery_to_response(d) -> DeliveryResponse:
    return DeliveryResponse(
        id=d.id,
        subscription_id=d.subscription_id,
        event_type=d.event_type,
        status=d.status.value,
        response_status=d.response_status,
        error=d.error,
        attempt=d.attempt,
        next_retry_at=d.next_retry_at.isoformat() if d.next_retry_at else None,
        created_at=d.created_at.isoformat(),
    )


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions() -> list[SubscriptionResponse]:
    container = get_container()
    subs = await container.webhook_management.list_subscriptions(_DEFAULT_TENANT)
    return [_sub_to_response(s) for s in subs]


@router.post(
    "",
    response_model=CreateSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(req: CreateSubscriptionRequest) -> CreateSubscriptionResponse:
    container = get_container()
    result = await container.webhook_management.create_subscription(
        _DEFAULT_TENANT, req.url, req.events
    )
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Validation Error",
            detail=result.error.message,
        )
    sub, secret = result.value
    return CreateSubscriptionResponse(
        subscription=_sub_to_response(sub),
        secret=secret,
    )


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(subscription_id: str) -> SubscriptionResponse:
    container = get_container()
    result = await container.webhook_management.get_subscription(_DEFAULT_TENANT, subscription_id)
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )
    return _sub_to_response(result.value)


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(subscription_id: str) -> None:
    container = get_container()
    result = await container.webhook_management.delete_subscription(
        _DEFAULT_TENANT, subscription_id
    )
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )


@router.post("/{subscription_id}/test", response_model=TestDeliveryResponse)
async def test_subscription(subscription_id: str) -> TestDeliveryResponse:
    container = get_container()
    result = await container.webhook_management.test_subscription(_DEFAULT_TENANT, subscription_id)
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )
    return TestDeliveryResponse(delivery=_delivery_to_response(result.value))


@router.get("/{subscription_id}/deliveries", response_model=list[DeliveryResponse])
async def list_deliveries(subscription_id: str, limit: int = 50) -> list[DeliveryResponse]:
    container = get_container()
    deliveries = await container.webhook_management.list_deliveries(subscription_id, limit)
    return [_delivery_to_response(d) for d in deliveries]
