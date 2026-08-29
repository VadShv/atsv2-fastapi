"""Тесты структурного логирования (JUGO-032).

Проверяют:
- Маскирование ПД (email, телефон) в лог-сообщениях
- Context variables: tenant_id, trace_id прокидываются в логи
- setup_logging не падает без structlog (stdlib fallback)
- Middleware устанавливает request_id/trace_id
- get_logger возвращает рабочий логгер
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.logging.context import (
    clear_context,
    get_all_context,
    get_log_context,
    set_context,
    set_log_context,
)
from ats.infra.logging.pii_mask import mask_pii_processor, _mask_string
from ats.infra.logging.settings import settings as log_settings
from ats.infra.logging.setup import get_logger, setup_logging


# --- Маскирование ПД ---

class TestPIIMasking:
    def test_mask_email(self) -> None:
        masked = _mask_string("Contact: john.doe@example.com")
        assert "john.doe@example.com" not in masked
        assert "jo***@example.com" in masked

    def test_mask_email_preserves_domain(self) -> None:
        masked = _mask_string("user@company.ru")
        assert "@company.ru" in masked
        assert "user@company.ru" not in masked

    def test_mask_phone(self) -> None:
        masked = _mask_string("Phone: +7 (999) 123-45-67")
        assert "+7 (999) 123-45-67" not in masked
        assert "***" in masked

    def test_mask_multiple_emails(self) -> None:
        masked = _mask_string("a@b.com and c@d.com")
        assert "a@b.com" not in masked
        assert "c@d.com" not in masked

    def test_no_masking_when_disabled(self) -> None:
        original = log_settings.mask_pii
        log_settings.mask_pii = False
        try:
            result = mask_pii_processor(
                None, "info", {"msg": "email: test@example.com"}
            )
            assert "test@example.com" in result["msg"]
        finally:
            log_settings.mask_pii = original

    def test_mask_in_processor(self) -> None:
        event_dict: dict[str, Any] = {"msg": "Contact test@example.com now"}
        result = mask_pii_processor(None, "info", event_dict)
        assert "test@example.com" not in result["msg"]
        assert "***" in result["msg"]

    def test_mask_nested_dict(self) -> None:
        event_dict: dict[str, Any] = {
            "data": {"email": "user@test.com", "nested": {"phone": "+79991234567"}}
        }
        result = mask_pii_processor(None, "info", event_dict)
        assert "user@test.com" not in result["data"]["email"]
        assert "+79991234567" not in result["data"]["nested"]["phone"]

    def test_mask_list_values(self) -> None:
        event_dict: dict[str, Any] = {"items": ["a@b.com", "normal text"]}
        result = mask_pii_processor(None, "info", event_dict)
        assert "a@b.com" not in result["items"][0]
        assert result["items"][1] == "normal text"

    def test_non_string_not_affected(self) -> None:
        event_dict: dict[str, Any] = {"count": 42, "ratio": 0.95, "flag": True}
        result = mask_pii_processor(None, "info", event_dict)
        assert result["count"] == 42
        assert result["ratio"] == 0.95
        assert result["flag"] is True


# --- Context variables ---

class TestLogContext:
    def test_set_and_get(self) -> None:
        set_context(tenant_id="t-123", trace_id="tr-456")
        assert get_log_context("tenant_id") == "t-123"
        assert get_log_context("trace_id") == "tr-456"

    def test_clear_context(self) -> None:
        set_context(tenant_id="t-123", user_id="u-1")
        clear_context()
        assert get_log_context("tenant_id") is None
        assert get_log_context("user_id") is None

    def test_get_all_context(self) -> None:
        set_context(tenant_id="t-1", trace_id="tr-1", user_id="u-1", request_id="r-1")
        ctx = get_all_context()
        assert ctx["tenant_id"] == "t-1"
        assert ctx["trace_id"] == "tr-1"
        assert ctx["user_id"] == "u-1"
        assert ctx["request_id"] == "r-1"
        clear_context()

    def test_set_log_context_individual(self) -> None:
        set_log_context("tenant_id", "t-789")
        assert get_log_context("tenant_id") == "t-789"
        clear_context()

    def test_get_unknown_key_returns_none(self) -> None:
        assert get_log_context("nonexistent") is None

    def test_set_unknown_key_noop(self) -> None:
        set_log_context("nonexistent", "value")  # не должно падать


# --- setup_logging ---

class TestSetupLogging:
    def test_setup_does_not_raise(self) -> None:
        setup_logging()

    def test_get_logger_returns_logger(self) -> None:
        setup_logging()
        lg = get_logger("test")
        assert lg is not None
        lg.info("test message")

    def test_get_logger_with_pii(self) -> None:
        setup_logging()
        lg = get_logger("test")
        lg.info("User email: test@example.com called")


# --- Middleware ---

class TestRequestContextMiddleware:
    def test_middleware_sets_request_id(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"request_id": get_log_context("request_id") or ""}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json()["request_id"] != ""
        assert response.headers.get("X-Request-Id") is not None

    def test_middleware_preserves_header_request_id(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"request_id": get_log_context("request_id") or ""}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-Id": "my-req-id"})
        assert response.json()["request_id"] == "my-req-id"
        assert response.headers["X-Request-Id"] == "my-req-id"

    def test_middleware_sets_trace_id(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"trace_id": get_log_context("trace_id") or ""}

        client = TestClient(app)
        response = client.get("/test")
        assert response.json()["trace_id"] != ""
        assert response.headers.get("X-Trace-Id") is not None

    def test_middleware_preserves_trace_id_header(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"trace_id": get_log_context("trace_id") or ""}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Trace-Id": "trace-abc"})
        assert response.json()["trace_id"] == "trace-abc"
        assert response.headers["X-Trace-Id"] == "trace-abc"

    def test_middleware_generates_unique_ids(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        ids: list[str] = []

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            ids.append(get_log_context("request_id") or "")
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")
        client.get("/test")
        assert len(ids) == 2
        assert ids[0] != ids[1]


# --- Настройки ---

class TestLogSettings:
    def test_defaults(self) -> None:
        assert log_settings.level == "INFO"
        assert log_settings.json_format is True
        assert log_settings.mask_pii is True

    def test_pii_name_visible_chars(self) -> None:
        assert log_settings.pii_name_visible_chars == 2

    def test_email_pattern_matches(self) -> None:
        import re

        pattern = re.compile(log_settings.pii_email_pattern)
        assert pattern.search("test@example.com")
        assert pattern.search("user.name+tag@domain.co.uk")

    def test_phone_pattern_matches(self) -> None:
        import re

        pattern = re.compile(log_settings.pii_phone_pattern)
        assert pattern.search("+7 (999) 123-45-67")
        assert pattern.search("88001234567")
