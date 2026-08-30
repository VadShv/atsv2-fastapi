"""Тесты OpenTelemetry трейсинга (JUGO-030).

Проверяют:
- Настройки TracingSettings (env: ATS_OTEL_*)
- No-op fallback: если OTel не установлен — функции не падают
- get_current_trace_id: синхронный доступ к trace_id
- TracingMiddleware: создаёт span, синхронизирует trace_id
- Propagation: capture/restore trace_context для воркеров
- BaseTask: восстанавливает trace_ctx из params
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.logging.context import clear_context, get_log_context, set_context
from ats.infra.tracing.context import (
    extract_trace_context,
    get_current_span_id,
    get_current_trace_id,
    get_trace_context_for_propagation,
    is_tracing_enabled,
)
from ats.infra.tracing.propagation import (
    capture_trace_context,
    restore_trace_context,
    with_trace_context,
)
from ats.infra.tracing.settings import settings as tracing_settings
from ats.infra.tracing.setup import get_tracer, setup_tracing

# --- Настройки ---


class TestTracingSettings:
    def test_defaults(self) -> None:
        assert tracing_settings.enabled is False
        assert tracing_settings.service_name == "ats-core"
        assert tracing_settings.service_version == "0.1.0"
        assert tracing_settings.otlp_protocol == "grpc"
        assert tracing_settings.propagate_to_workers is True

    def test_otlp_endpoint_default(self) -> None:
        assert "4317" in tracing_settings.otlp_endpoint

    def test_sampler_default(self) -> None:
        assert tracing_settings.traces_sampler == "parentbased_always_on"


# --- No-op fallback ---


class TestNoOpFallback:
    def test_setup_tracing_does_not_raise_without_otel(self) -> None:
        """setup_tracing() не падает, даже если OTel не установлен."""
        setup_tracing()

    def test_get_tracer_returns_object(self) -> None:
        """get_tracer всегда возвращает объект с start_as_current_span."""
        tracer = get_tracer("test")
        assert tracer is not None
        span = tracer.start_as_current_span("test-span")
        assert span is not None

    def test_noop_span_context_manager(self) -> None:
        """No-op span работает как context manager."""
        tracer = get_tracer("test")
        with tracer.start_as_current_span("test") as span:
            span.set_attribute("key", "value")
            span.set_attribute("count", 42)
            assert span is not None

    def test_is_tracing_enabled(self) -> None:
        """Возвращает bool (True если OTel установлен, False если нет)."""
        result = is_tracing_enabled()
        assert isinstance(result, bool)


# --- Context functions ---


class TestTracingContext:
    def test_get_current_trace_id_from_contextvars(self) -> None:
        """Если OTel не установлен, trace_id берётся из contextvars."""
        clear_context()
        set_context(trace_id="test-trace-123")
        trace_id = get_current_trace_id()
        assert trace_id == "test-trace-123"
        clear_context()

    def test_get_current_trace_id_none_when_empty(self) -> None:
        clear_context()
        trace_id = get_current_trace_id()
        assert trace_id is None

    def test_get_current_span_id_none_without_otel(self) -> None:
        """Если OTel не установлен, span_id = None."""
        span_id = get_current_span_id()
        assert span_id is None

    def test_get_trace_context_for_propagation_fallback(self) -> None:
        """Если OTel не установлен, прокидывается x-trace-id из contextvars."""
        clear_context()
        set_context(trace_id="trace-abc")
        headers = get_trace_context_for_propagation()
        assert "x-trace-id" in headers
        assert headers["x-trace-id"] == "trace-abc"
        clear_context()

    def test_get_trace_context_empty_when_no_trace(self) -> None:
        clear_context()
        headers = get_trace_context_for_propagation()
        assert headers == {}

    def test_extract_trace_context_from_custom_header(self) -> None:
        """Извлечение trace_id из x-trace-id заголовка (fallback)."""
        headers = {"x-trace-id": "trace-xyz"}
        trace_id = extract_trace_context(headers)
        assert trace_id == "trace-xyz"

    def test_extract_trace_context_from_uppercase_header(self) -> None:
        headers = {"X-Trace-Id": "trace-upper"}
        trace_id = extract_trace_context(headers)
        assert trace_id == "trace-upper"

    def test_extract_trace_context_empty(self) -> None:
        trace_id = extract_trace_context({})
        assert trace_id is None


# --- Propagation ---


class TestTracePropagation:
    def test_capture_trace_context(self) -> None:
        """capture_trace_context возвращает dict заголовков."""
        clear_context()
        set_context(trace_id="trace-cap")
        headers = capture_trace_context()
        assert isinstance(headers, dict)
        assert headers.get("x-trace-id") == "trace-cap"
        clear_context()

    def test_restore_trace_context_sets_contextvar(self) -> None:
        """restore_trace_context устанавливает trace_id в contextvars."""
        clear_context()
        headers = {"x-trace-id": "restored-trace"}
        trace_id = restore_trace_context(headers)
        assert trace_id == "restored-trace"
        assert get_log_context("trace_id") == "restored-trace"
        clear_context()

    def test_restore_trace_context_empty_headers(self) -> None:
        """restore_trace_context с пустыми заголовками не падает."""
        result = restore_trace_context(None)
        assert result is None

    def test_restore_trace_context_no_headers_key(self) -> None:
        result = restore_trace_context({})
        assert result is None

    def test_with_trace_context_context_manager(self) -> None:
        """with_trace_context работает как context manager."""
        clear_context()
        headers = {"x-trace-id": "ctx-mgr-trace"}
        with with_trace_context(headers):
            assert get_log_context("trace_id") == "ctx-mgr-trace"
        clear_context()

    def test_roundtrip_capture_restore(self) -> None:
        """Полный цикл: capture → restore сохраняет trace_id."""
        clear_context()
        set_context(trace_id="roundtrip-123")
        headers = capture_trace_context()

        clear_context()
        assert get_log_context("trace_id") is None

        restored = restore_trace_context(headers)
        assert restored == "roundtrip-123"
        assert get_log_context("trace_id") == "roundtrip-123"
        clear_context()


# --- TracingMiddleware ---


class TestTracingMiddleware:
    def test_middleware_does_not_raise(self) -> None:
        """TracingMiddleware не падает без OTel SDK."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.tracing import TracingMiddleware

        app = FastAPI()
        app.add_middleware(TracingMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_middleware_with_request_context(self) -> None:
        """TracingMiddleware + RequestContextMiddleware вместе работают."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware
        from ats.infra.tracing import TracingMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)
        app.add_middleware(TracingMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {
                "trace_id": get_log_context("trace_id") or "",
                "request_id": get_log_context("request_id") or "",
            }

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] != ""
        assert data["request_id"] != ""

    def test_middleware_preserves_incoming_trace_id(self) -> None:
        """Входящий X-Trace-Id сохраняется в contextvars."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.logging import RequestContextMiddleware
        from ats.infra.tracing import TracingMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)
        app.add_middleware(TracingMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"trace_id": get_log_context("trace_id") or ""}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Trace-Id": "incoming-trace"})
        assert response.json()["trace_id"] == "incoming-trace"

    def test_middleware_records_error_status(self) -> None:
        """Middleware не падает при 500-й ошибке в endpoint."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.tracing import TracingMiddleware

        app = FastAPI()
        app.add_middleware(TracingMiddleware)

        @app.get("/error")
        async def error_endpoint() -> dict[str, str]:
            raise RuntimeError("test error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/error")
        assert response.status_code == 500


# --- BaseTask trace integration ---


class TestBaseTaskTraceIntegration:
    async def test_base_task_pops_trace_ctx(self) -> None:
        """BaseTask извлекает trace_ctx из params и восстанавливает trace_id."""
        from ats.infra.workers.base_task import BaseTask

        class TestTask(BaseTask):
            name = "test_task"
            captured_trace_id: str | None = None

            async def execute(self, ctx: Any, **params: Any) -> dict[str, Any] | None:
                self.captured_trace_id = ctx.trace_id
                return {"ok": True}

        clear_context()
        task = TestTask()
        result = await task(
            ctx={"job_id": "job-1"},
            trace_ctx={"x-trace-id": "task-trace-123"},
            data="test",
        )
        assert result["trace_id"] == "task-trace-123"
        assert task.captured_trace_id == "task-trace-123"
        clear_context()

    async def test_base_task_without_trace_ctx(self) -> None:
        """BaseTask работает без trace_ctx в params."""
        from ats.infra.workers.base_task import BaseTask

        class TestTask(BaseTask):
            name = "test_task_no_trace"

            async def execute(self, ctx: Any, **params: Any) -> dict[str, Any] | None:
                return {"ok": True}

        task = TestTask()
        result = await task(ctx={"job_id": "job-2"})
        assert result["trace_id"] is None
        assert result["success"] is True

    async def test_base_task_trace_ctx_removed_from_params(self) -> None:
        """trace_ctx не передаётся в execute() как обычный параметр."""
        from ats.infra.workers.base_task import BaseTask

        class TestTask(BaseTask):
            name = "test_task_params"

            async def execute(self, ctx: Any, **params: Any) -> dict[str, Any] | None:
                # trace_ctx не должен быть в params
                assert "trace_ctx" not in params
                return {"params": list(params.keys())}

        task = TestTask()
        result = await task(
            ctx={"job_id": "job-3"},
            trace_ctx={"x-trace-id": "trace"},
            real_param="value",
        )
        assert result["success"] is True
        assert "trace_ctx" not in result["metadata"]["params"]


# --- Интеграция: trace_id в логах и аудите ---


class TestTraceIdIntegration:
    def test_trace_id_available_after_context_set(self) -> None:
        """trace_id доступен синхронно после установки в contextvars."""
        clear_context()
        set_context(trace_id="integration-trace")

        # get_current_trace_id должен вернуть то же значение
        trace_id = get_current_trace_id()
        assert trace_id == "integration-trace"

        # И оно должно быть в лог-контексте
        assert get_log_context("trace_id") == "integration-trace"
        clear_context()
