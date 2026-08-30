"""Tests for JUGO-192: Webhooks — domain, repository, use cases, API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.infra.middleware import reset_idempotency_store, reset_rate_limit_store
from ats.infra.stubs_webhooks import (
    InMemoryWebhookDeliveryRepository,
    InMemoryWebhookSubscriptionRepository,
)
from ats.main import app
from ats.modules.webhooks.application.webhook_use_cases import (
    WebhookDispatcher,
    WebhookManagementUseCase,
)
from ats.modules.webhooks.domain.webhook import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookStatus,
    WebhookSubscription,
    build_signature_header,
    sign_payload,
    verify_signature,
    verify_signed_header,
)
from ats.shared.events import DomainEvent
from ats.shared.ids import TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_container()
    reset_idempotency_store()
    reset_rate_limit_store()


# ===========================================================================
# Domain: WebhookSubscription
# ===========================================================================


class TestWebhookSubscription:
    def test_create_subscription(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["application.created"]
        )
        assert sub.url == "https://example.com/wh"
        assert sub.events == ["application.created"]
        assert sub.status == WebhookStatus.ACTIVE
        assert len(sub.secret) > 0

    def test_create_generates_secret(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"]
        )
        assert sub.secret  # non-empty
        assert len(sub.secret) >= 32

    def test_create_with_custom_secret(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value,
            url="https://example.com/wh",
            events=["*"],
            secret="my-secret",
        )
        assert sub.secret == "my-secret"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="http"):
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="ftp://bad", events=["*"]
            )

    def test_empty_events_raises(self) -> None:
        with pytest.raises(ValueError, match="event"):
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="https://example.com/wh", events=[]
            )

    def test_matches_event_exact(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value,
            url="https://example.com/wh",
            events=["application.created", "application.rejected"],
        )
        assert sub.matches_event("application.created")
        assert sub.matches_event("application.rejected")
        assert not sub.matches_event("vacancy.created")

    def test_matches_event_wildcard(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"]
        )
        assert sub.matches_event("any.event.type")

    def test_mark_degraded(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"]
        )
        degraded = sub.mark_degraded()
        assert degraded.status == WebhookStatus.DEGRADED
        assert sub.status == WebhookStatus.ACTIVE  # immutable

    def test_disable(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"]
        )
        disabled = sub.disable()
        assert disabled.status == WebhookStatus.DISABLED
        assert not disabled.is_deliverable()

    def test_is_deliverable(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"]
        )
        assert sub.is_deliverable()
        assert sub.mark_degraded().is_deliverable()
        assert not sub.disable().is_deliverable()

    def test_to_public_dict_excludes_secret(self) -> None:
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"], secret="secret123"
        )
        d = sub.to_public_dict()
        assert "secret" not in d
        assert d["url"] == "https://example.com/wh"
        assert d["status"] == "active"


# ===========================================================================
# Domain: HMAC signing
# ===========================================================================


class TestHmacSigning:
    def test_sign_and_verify(self) -> None:
        body = b'{"event": "test"}'
        secret = "my-secret"
        signature = sign_payload(body, secret)
        assert signature.startswith("sha256=")
        assert verify_signature(body, signature, secret)

    def test_verify_wrong_secret(self) -> None:
        body = b'{"event": "test"}'
        signature = sign_payload(body, "correct-secret")
        assert not verify_signature(body, signature, "wrong-secret")

    def test_verify_tampered_body(self) -> None:
        body = b'{"event": "test"}'
        signature = sign_payload(body, "secret")
        assert not verify_signature(b'{"event": "hacked"}', signature, "secret")

    def test_build_signed_header(self) -> None:
        body = b'{"event": "test"}'
        header = build_signature_header(body, "secret")
        assert header.startswith("t=")
        assert "sha256=" in header

    def test_verify_signed_header(self) -> None:
        body = b'{"event": "test"}'
        header = build_signature_header(body, "secret")
        assert verify_signed_header(body, header, "secret")

    def test_verify_signed_header_wrong_secret(self) -> None:
        body = b'{"event": "test"}'
        header = build_signature_header(body, "correct")
        assert not verify_signed_header(body, header, "wrong")

    def test_verify_signed_header_replay_rejected(self) -> None:
        """Expired timestamp -> rejected (replay protection)."""
        body = b'{"event": "test"}'
        old_ts = datetime.now(UTC).timestamp() - 600  # 10 min ago
        ts_body = f"{int(old_ts)}.".encode() + body
        import hashlib
        import hmac

        sig = hmac.new(b"secret", ts_body, hashlib.sha256).hexdigest()
        header = f"t={int(old_ts)},sha256={sig}"
        assert not verify_signed_header(body, header, "secret")

    def test_verify_malformed_header(self) -> None:
        assert not verify_signed_header(b"body", "malformed", "secret")
        assert not verify_signed_header(b"body", "", "secret")


# ===========================================================================
# Domain: WebhookDelivery
# ===========================================================================


class TestWebhookDelivery:
    def test_create_pending(self) -> None:
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test.event", payload='{"ok": true}'
        )
        assert d.status == DeliveryStatus.PENDING
        assert d.attempt == 0
        assert d.is_terminal() is False

    def test_mark_delivered(self) -> None:
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test.event", payload="{}"
        )
        delivered = d.mark_delivered(200, "OK")
        assert delivered.status == DeliveryStatus.DELIVERED
        assert delivered.response_status == 200
        assert delivered.is_terminal()

    def test_mark_retry(self) -> None:
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test.event", payload="{}"
        )
        retry = d.mark_retry("HTTP 500", 500)
        assert retry.status == DeliveryStatus.RETRY
        assert retry.attempt == 1
        assert retry.next_retry_at is not None
        assert retry.error == "HTTP 500"

    def test_mark_failed(self) -> None:
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test.event", payload="{}"
        )
        failed = d.mark_failed("Connection refused")
        assert failed.status == DeliveryStatus.FAILED
        assert failed.is_terminal()

    def test_to_public_dict(self) -> None:
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test.event", payload="{}"
        )
        d_dict = d.to_public_dict()
        assert d_dict["status"] == "pending"
        assert d_dict["event_type"] == "test.event"


# ===========================================================================
# Repository: InMemoryWebhookSubscriptionRepository
# ===========================================================================


class TestInMemorySubscriptionRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        repo = InMemoryWebhookSubscriptionRepository()
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://example.com/wh", events=["*"]
        )
        await repo.save(sub)
        fetched = await repo.get_by_id(TENANT, str(sub.id))
        assert fetched is not None
        assert fetched.url == sub.url

    @pytest.mark.asyncio
    async def test_list_all(self) -> None:
        repo = InMemoryWebhookSubscriptionRepository()
        await repo.save(
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="https://a.com/wh", events=["*"]
            )
        )
        await repo.save(
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="https://b.com/wh", events=["*"]
            )
        )
        all_subs = await repo.list_all(TENANT)
        assert len(all_subs) == 2

    @pytest.mark.asyncio
    async def test_find_by_event(self) -> None:
        repo = InMemoryWebhookSubscriptionRepository()
        await repo.save(
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="https://a.com/wh", events=["application.created"]
            )
        )
        await repo.save(
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="https://b.com/wh", events=["vacancy.created"]
            )
        )
        matches = await repo.find_by_event(TENANT, "application.created")
        assert len(matches) == 1
        assert matches[0].url == "https://a.com/wh"

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        repo = InMemoryWebhookSubscriptionRepository()
        sub = WebhookSubscription.create(
            tenant_id=TENANT.value, url="https://a.com/wh", events=["*"]
        )
        await repo.save(sub)
        assert await repo.delete(TENANT, str(sub.id)) is True
        assert await repo.get_by_id(TENANT, str(sub.id)) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self) -> None:
        repo = InMemoryWebhookSubscriptionRepository()
        assert await repo.delete(TENANT, "nonexistent") is False

    @pytest.mark.asyncio
    async def test_tenant_isolation(self) -> None:
        repo = InMemoryWebhookSubscriptionRepository()
        tenant2 = TenantId.from_string("00000000-0000-0000-0000-000000000002")
        await repo.save(
            WebhookSubscription.create(
                tenant_id=TENANT.value, url="https://a.com/wh", events=["*"]
            )
        )
        await repo.save(
            WebhookSubscription.create(
                tenant_id=tenant2.value, url="https://b.com/wh", events=["*"]
            )
        )
        assert len(await repo.list_all(TENANT)) == 1
        assert len(await repo.list_all(tenant2)) == 1


# ===========================================================================
# Repository: InMemoryWebhookDeliveryRepository
# ===========================================================================


class TestInMemoryDeliveryRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        repo = InMemoryWebhookDeliveryRepository()
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test", payload="{}"
        )
        await repo.save(d)
        fetched = await repo.get_by_id(str(d.id))
        assert fetched is not None
        assert fetched.event_type == "test"

    @pytest.mark.asyncio
    async def test_list_by_subscription(self) -> None:
        repo = InMemoryWebhookDeliveryRepository()
        sub_id = TENANT.value
        for _ in range(3):
            await repo.save(
                WebhookDelivery.create_pending(
                    subscription_id=sub_id, event_type="test", payload="{}"
                )
            )
        deliveries = await repo.list_by_subscription(str(sub_id))
        assert len(deliveries) == 3

    @pytest.mark.asyncio
    async def test_list_pending_retries(self) -> None:
        repo = InMemoryWebhookDeliveryRepository()
        d = WebhookDelivery.create_pending(
            subscription_id=TENANT.value, event_type="test", payload="{}"
        )
        d = d.mark_retry("failed")
        await repo.save(d)
        # next_retry_at is in the future, so no pending yet
        pending = await repo.list_pending_retries()
        assert len(pending) == 0

        # Manually set next_retry_at to past
        d_past = WebhookDelivery(
            id=d.id,
            subscription_id=d.subscription_id,
            event_type=d.event_type,
            payload=d.payload,
            status=DeliveryStatus.RETRY,
            attempt=1,
            next_retry_at=datetime.now(UTC) - timedelta(minutes=1),
            created_at=d.created_at,
        )
        await repo.save(d_past)
        pending = await repo.list_pending_retries()
        assert len(pending) == 1


# ===========================================================================
# Use Case: WebhookManagementUseCase
# ===========================================================================


class TestWebhookManagementUseCase:
    @pytest.mark.asyncio
    async def test_create_subscription(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        uc = WebhookManagementUseCase(sub_repo, deliv_repo)

        result = await uc.create_subscription(TENANT, "https://example.com/wh", ["*"])
        assert not is_error(result)
        sub, secret = result.value
        assert sub.url == "https://example.com/wh"
        assert secret  # secret returned

    @pytest.mark.asyncio
    async def test_create_invalid_url(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        uc = WebhookManagementUseCase(sub_repo, deliv_repo)

        result = await uc.create_subscription(TENANT, "ftp://bad", ["*"])
        assert is_error(result)
        assert "http" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_get_subscription(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        uc = WebhookManagementUseCase(sub_repo, deliv_repo)

        create_result = await uc.create_subscription(TENANT, "https://example.com/wh", ["*"])
        sub_id = str(create_result.value[0].id)

        get_result = await uc.get_subscription(TENANT, sub_id)
        assert not is_error(get_result)
        assert get_result.value.url == "https://example.com/wh"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        uc = WebhookManagementUseCase(sub_repo, deliv_repo)

        result = await uc.get_subscription(TENANT, "nonexistent")
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_list_subscriptions(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        uc = WebhookManagementUseCase(sub_repo, deliv_repo)

        await uc.create_subscription(TENANT, "https://a.com/wh", ["*"])
        await uc.create_subscription(TENANT, "https://b.com/wh", ["*"])
        subs = await uc.list_subscriptions(TENANT)
        assert len(subs) == 2

    @pytest.mark.asyncio
    async def test_delete_subscription(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        uc = WebhookManagementUseCase(sub_repo, deliv_repo)

        create_result = await uc.create_subscription(TENANT, "https://example.com/wh", ["*"])
        sub_id = str(create_result.value[0].id)

        delete_result = await uc.delete_subscription(TENANT, sub_id)
        assert not is_error(delete_result)

        # Verify deleted
        get_result = await uc.get_subscription(TENANT, sub_id)
        assert is_error(get_result)


# ===========================================================================
# Use Case: WebhookDispatcher
# ===========================================================================


class TestWebhookDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_finds_matching_subscriptions(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        management = WebhookManagementUseCase(sub_repo, deliv_repo)
        dispatcher = WebhookDispatcher(sub_repo, deliv_repo, management)

        await management.create_subscription(
            TENANT, "https://example.com/wh", ["application.created"]
        )

        from uuid import uuid4

        from ats.modules.recruitment.domain.application import ApplicationCreated

        event = ApplicationCreated(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            tenant_id=TENANT.value,
            application_id=uuid4(),
            candidate_id=uuid4(),
            vacancy_id=uuid4(),
        )

        deliveries = await dispatcher.dispatch_event(event)
        # Delivery will fail (example.com doesn't accept), but delivery record is created
        assert len(deliveries) == 1

    @pytest.mark.asyncio
    async def test_dispatch_no_matching_subscriptions(self) -> None:
        sub_repo = InMemoryWebhookSubscriptionRepository()
        deliv_repo = InMemoryWebhookDeliveryRepository()
        management = WebhookManagementUseCase(sub_repo, deliv_repo)
        dispatcher = WebhookDispatcher(sub_repo, deliv_repo, management)

        from uuid import uuid4

        from ats.modules.recruitment.domain.vacancy import VacancyCreated

        event = VacancyCreated(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            tenant_id=TENANT.value,
            vacancy_id=uuid4(),
        )

        deliveries = await dispatcher.dispatch_event(event)
        assert len(deliveries) == 0


# ===========================================================================
# API: Webhook endpoints
# ===========================================================================


class TestWebhookAPI:
    def test_list_empty(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/webhooks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_list(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh", "events": ["application.created"]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "secret" in body
        assert body["subscription"]["url"] == "https://example.com/wh"

        # List should now have 1
        resp = client.get("/api/v1/webhooks")
        assert len(resp.json()) == 1

    def test_get_by_id(self) -> None:
        client = TestClient(app)
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh", "events": ["*"]},
        )
        sub_id = create_resp.json()["subscription"]["id"]

        resp = client.get(f"/api/v1/webhooks/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://example.com/wh"

    def test_get_nonexistent_returns_404(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/webhooks/nonexistent-id")
        assert resp.status_code == 404
        assert resp.headers["content-type"] == "application/problem+json"

    def test_delete(self) -> None:
        client = TestClient(app)
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh", "events": ["*"]},
        )
        sub_id = create_resp.json()["subscription"]["id"]

        resp = client.delete(f"/api/v1/webhooks/{sub_id}")
        assert resp.status_code == 204

        # Verify deleted
        resp = client.get(f"/api/v1/webhooks/{sub_id}")
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self) -> None:
        client = TestClient(app)
        resp = client.delete("/api/v1/webhooks/nonexistent")
        assert resp.status_code == 404

    def test_test_subscription(self) -> None:
        client = TestClient(app)
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh", "events": ["*"]},
        )
        sub_id = create_resp.json()["subscription"]["id"]

        resp = client.post(f"/api/v1/webhooks/{sub_id}/test")
        assert resp.status_code == 200
        assert "delivery" in resp.json()
        assert resp.json()["delivery"]["event_type"] == "webhook.test"

    def test_list_deliveries(self) -> None:
        client = TestClient(app)
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh", "events": ["*"]},
        )
        sub_id = create_resp.json()["subscription"]["id"]

        # Send a test to create a delivery
        client.post(f"/api/v1/webhooks/{sub_id}/test")

        resp = client.get(f"/api/v1/webhooks/{sub_id}/deliveries")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_create_invalid_url_returns_400(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "ftp://bad", "events": ["*"]},
        )
        assert resp.status_code == 400
        assert resp.headers["content-type"] == "application/problem+json"
