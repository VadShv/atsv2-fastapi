"""Тесты Sentry + алертов (JUGO-034).

Проверяют:
- Настройки SentrySettings (env: ATS_SENTRY_*)
- No-op fallback: если sentry-sdk не установлен — функции не падают
- setup_sentry: не падает без DSN и без sentry-sdk
- capture_exception: best-effort, не падает
- capture_message: best-effort, не падает
- set_user_context: best-effort, не падает
- send_alert: не отправляет без webhook URL
- SentryMiddleware: перехватывает исключения
- Alert payload: Telegram/Slack формат
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.logging.context import clear_context, set_context
from ats.infra.sentry.alerts import _build_payload, _should_alert, send_alert
from ats.infra.sentry.settings import settings as sentry_settings
from ats.infra.sentry.setup import (
    capture_exception,
    capture_message,
    is_sentry_enabled,
    set_user_context,
    setup_sentry,
)


# --- Настройки ---

class TestSentrySettings:
    def test_defaults(self) -> None:
        assert sentry_settings.dsn == ""
        assert sentry_settings.environment == "dev"
        assert sentry_settings.send_default_pii is False
        assert sentry_settings.traces_sample_rate == 0.0
        assert sentry_settings.max_breadcrumbs == 100
        assert sentry_settings.attach_stacktrace is True
        assert sentry_settings.alert_webhook_url == ""
        assert sentry_settings.alert_min_level == "ERROR"

    def test_release_format(self) -> None:
        assert "@" in sentry_settings.release


# --- No-op fallback ---

class TestNoOpSentry:
    def test_setup_sentry_does_not_raise_without_dsn(self) -> None:
        """setup_sentry() не падает без DSN."""
        setup_sentry()

    def test_is_sentry_enabled_returns_bool(self) -> None:
        result = is_sentry_enabled()
        assert isinstance(result, bool)

    def test_capture_exception_does_not_raise(self) -> None:
        """capture_exception не падает без Sentry."""
        try:
            raise ValueError("test error")
        except ValueError as exc:
            capture_exception(exc, tags={"test": "tag"}, extra={"key": "val"})

    def test_capture_message_does_not_raise(self) -> None:
        capture_message("test message", level="warning")

    def test_set_user_context_does_not_raise(self) -> None:
        set_user_context(user_id="u-123", tenant_id="t-456", email="test@test.com")


# --- Alerts ---

class TestAlerts:
    async def test_send_alert_no_webhook(self) -> None:
        """send_alert возвращает False без webhook URL."""
        result = await send_alert(
            title="Test alert",
            message="test message",
            level="ERROR",
        )
        assert result is False

    async def test_send_alert_low_level_filtered(self) -> None:
        """Алерты ниже минимального уровня не отправляются."""
        # alert_min_level = ERROR по умолчанию
        result = await send_alert(
            title="Test",
            message="info message",
            level="INFO",
        )
        assert result is False


class TestShouldAlert:
    def test_error_alerts(self) -> None:
        assert _should_alert("ERROR") is True

    def test_critical_alerts(self) -> None:
        assert _should_alert("CRITICAL") is True

    def test_warning_filtered_by_default(self) -> None:
        # alert_min_level = ERROR
        assert _should_alert("WARNING") is False

    def test_info_filtered(self) -> None:
        assert _should_alert("INFO") is False


class TestBuildPayload:
    def test_telegram_payload(self) -> None:
        """Payload для Telegram содержит text и parse_mode."""
        # Сохраняем и восстанавливаем webhook URL
        original_url = sentry_settings.alert_webhook_url
        sentry_settings.alert_webhook_url = "https://api.telegram.org/bot123/sendMessage"
        try:
            payload = _build_payload(
                title="Test Alert",
                message="Something went wrong",
                level="ERROR",
                trace_id="trace-abc",
                extra={"key": "value"},
            )
            assert "text" in payload
            assert "parse_mode" in payload
            assert "Test Alert" in payload["text"]
            assert "trace-abc" in payload["text"]
            assert "Something went wrong" in payload["text"]
        finally:
            sentry_settings.alert_webhook_url = original_url

    def test_slack_payload(self) -> None:
        """Payload для Slack содержит text."""
        original_url = sentry_settings.alert_webhook_url
        sentry_settings.alert_webhook_url = "https://hooks.slack.com/services/xxx"
        try:
            payload = _build_payload(
                title="Slack Alert",
                message="Error occurred",
                level="CRITICAL",
                trace_id="trace-xyz",
                extra=None,
            )
            assert "text" in payload
            assert "Slack Alert" in payload["text"]
        finally:
            sentry_settings.alert_webhook_url = original_url

    def test_payload_contains_emoji(self) -> None:
        payload = _build_payload(
            title="Alert",
            message="msg",
            level="ERROR",
            trace_id="",
            extra=None,
        )
        assert "🔴" in payload["text"]

    def test_payload_critical_emoji(self) -> None:
        payload = _build_payload(
            title="Alert",
            message="msg",
            level="CRITICAL",
            trace_id="",
            extra=None,
        )
        assert "🚨" in payload["text"]

    def test_payload_includes_environment(self) -> None:
        payload = _build_payload(
            title="Alert",
            message="msg",
            level="ERROR",
            trace_id="",
            extra=None,
        )
        assert sentry_settings.environment in payload["text"]

    def test_payload_truncates_extra_values(self) -> None:
        long_value = "x" * 500
        payload = _build_payload(
            title="Alert",
            message="msg",
            level="ERROR",
            trace_id="",
            extra={"data": long_value},
        )
        # Значение должно быть обрезано до 200 символов
        assert long_value not in payload["text"]


# --- SentryMiddleware ---

class TestSentryMiddleware:
    def test_middleware_passes_normal_requests(self) -> None:
        """Middleware пропускает нормальные запросы без исключений."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.sentry import SentryMiddleware

        app = FastAPI()
        app.add_middleware(SentryMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_middleware_captures_exception(self) -> None:
        """Middleware перехватывает исключения и пробрасывает их дальше."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.sentry import SentryMiddleware

        app = FastAPI()
        app.add_middleware(SentryMiddleware)

        @app.get("/error")
        async def error_endpoint() -> dict[str, str]:
            raise RuntimeError("test error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/error")
        assert response.status_code == 500


# --- Интеграция с полным app ---

class TestFullAppSentry:
    def test_app_starts_with_sentry(self) -> None:
        """Приложение запускается с Sentry middleware (no-op)."""
        from ats.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_app_error_does_not_crash(self) -> None:
        """500-я ошибка перехватывается, приложение не падает."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.sentry import SentryMiddleware

        app = FastAPI()
        app.add_middleware(SentryMiddleware)

        @app.get("/crash")
        async def crash_endpoint() -> dict[str, str]:
            raise ValueError("crash test")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/crash")
        assert response.status_code == 500
