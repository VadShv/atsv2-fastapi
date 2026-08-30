"""Tests for JUGO-190: Idempotency-Key, RFC 9457 errors, trace_id."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.infra.middleware import (
    reset_idempotency_store,
    reset_rate_limit_store,
)
from ats.main import app


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_container()
    reset_idempotency_store()
    reset_rate_limit_store()


class TestTraceId:
    """trace_id middleware: trace_id in headers."""

    def test_response_has_trace_id(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "X-Trace-Id" in resp.headers
        assert len(resp.headers["X-Trace-Id"]) > 0

    def test_client_trace_id_preserved(self) -> None:
        client = TestClient(app)
        custom_trace = "my-custom-trace-id-123"
        resp = client.get("/health", headers={"X-Trace-Id": custom_trace})
        assert resp.headers["X-Trace-Id"] == custom_trace

    def test_trace_id_is_hex(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        trace_id = resp.headers["X-Trace-Id"]
        assert all(c in "0123456789abcdef" for c in trace_id)
        assert len(trace_id) == 32


class TestProblemDetails:
    """RFC 9457 problem+json error responses."""

    def test_404_returns_problem_json(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/webhooks/nonexistent-id")
        assert resp.status_code == 404
        assert resp.headers["content-type"] == "application/problem+json"
        body = resp.json()
        assert body["type"] == "about:blank"
        assert body["title"] == "Not Found"
        assert body["status"] == 404
        assert "trace_id" in body
        assert body["trace_id"]  # non-empty

    def test_validation_error_has_errors_array(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "not-a-url", "events": []},
        )
        assert resp.status_code in (400, 422)
        assert resp.headers["content-type"] == "application/problem+json"
        body = resp.json()
        assert "errors" in body
        assert "trace_id" in body

    def test_problem_has_trace_id_header(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/webhooks/nonexistent")
        assert "X-Trace-Id" in resp.headers
        body = resp.json()
        assert "trace_id" in body
        assert body["trace_id"]  # non-empty


class TestIdempotency:
    """Idempotency-Key middleware: POST replay returns cached response."""

    def test_idempotent_post_replays_response(self) -> None:
        client = TestClient(app)
        key = "test-idem-key-001"
        body = {
            "url": "https://example.com/webhook",
            "events": ["application.created"],
        }

        resp1 = client.post(
            "/api/v1/webhooks",
            json=body,
            headers={"Idempotency-Key": key},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/api/v1/webhooks",
            json=body,
            headers={"Idempotency-Key": key},
        )
        assert resp2.status_code == 201
        assert resp2.headers.get("X-Idempotent-Replay") == "true"
        assert resp1.json()["subscription"]["id"] == resp2.json()["subscription"]["id"]

    def test_different_body_same_key_returns_422(self) -> None:
        client = TestClient(app)
        key = "test-idem-conflict-001"

        resp1 = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh1", "events": ["a"]},
            headers={"Idempotency-Key": key},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh2", "events": ["b"]},
            headers={"Idempotency-Key": key},
        )
        assert resp2.status_code == 422
        assert resp2.headers["content-type"] == "application/problem+json"
        assert "Idempotency" in resp2.json()["title"]

    def test_no_key_no_replay(self) -> None:
        """POST without Idempotency-Key is not cached."""
        client = TestClient(app)
        body = {"url": "https://example.com/wh", "events": ["test.event"]}

        resp1 = client.post("/api/v1/webhooks", json=body)
        resp2 = client.post("/api/v1/webhooks", json=body)

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert "X-Idempotent-Replay" not in resp2.headers
        # Different IDs — two separate creations
        assert resp1.json()["subscription"]["id"] != resp2.json()["subscription"]["id"]

    def test_get_requests_not_idempotent_cached(self) -> None:
        """Idempotency-Key only works for POST."""
        client = TestClient(app)
        resp = client.get("/health", headers={"Idempotency-Key": "some-key"})
        assert resp.status_code == 200
        assert "X-Idempotent-Replay" not in resp.headers


class TestRateLimitHeaders:
    """JUGO-191: X-RateLimit-* headers on all responses."""

    def test_response_has_rate_limit_headers(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers

    def test_read_limit_is_600(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.headers["X-RateLimit-Limit"] == "600"

    def test_write_limit_is_120(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://example.com/wh", "events": ["test"]},
        )
        assert resp.status_code == 201
        assert resp.headers["X-RateLimit-Limit"] == "120"

    def test_remaining_decreases(self) -> None:
        client = TestClient(app)
        resp1 = client.get("/health")
        resp2 = client.get("/health")
        remaining1 = int(resp1.headers["X-RateLimit-Remaining"])
        remaining2 = int(resp2.headers["X-RateLimit-Remaining"])
        assert remaining2 == remaining1 - 1


class TestIdempotencyStore:
    """Direct store tests."""

    def test_store_get_set_clear(self) -> None:
        from ats.infra.middleware.idempotency import CachedResponse, IdempotencyStore

        store = IdempotencyStore()
        cached = CachedResponse(status_code=201, body=b'{"ok": true}')
        store.set("key1", cached)

        result = store.get("key1")
        assert result is not None
        assert result.status_code == 201
        assert result.body == b'{"ok": true}'

        store.clear()
        assert store.get("key1") is None

    def test_store_returns_none_for_missing(self) -> None:
        from ats.infra.middleware.idempotency import IdempotencyStore

        store = IdempotencyStore()
        assert store.get("nonexistent") is None

    def test_store_cleanup_expired(self) -> None:
        from ats.infra.middleware.idempotency import CachedResponse, IdempotencyStore

        store = IdempotencyStore()
        # Create an expired entry by manipulating cached_at
        import time

        cached = CachedResponse(status_code=200, body=b"ok")
        # Manually set cached_at to past
        store._store["expired"] = CachedResponse(
            status_code=200, body=b"old", cached_at=time.time() - 100000
        )
        store._store["fresh"] = cached

        removed = store.cleanup_expired()
        assert removed == 1
        assert store.get("expired") is None
        assert store.get("fresh") is not None
