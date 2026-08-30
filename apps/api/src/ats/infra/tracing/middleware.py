"""Middleware для трейсинга HTTP-запросов (JUGO-030).

Интегрирует OTel spans с существующим RequestContextMiddleware:
- Создаёт span для каждого HTTP-запроса
- Прокидывает trace_id из OTel span в contextvars (для логов/аудита)
- Принимает входящий W3C traceparent (распределённые трейсы)
- Добавляет span-атрибуты: HTTP method, path, status, tenant_id
-WHITEBOX AI: tenant_id в span-атрибутах для фильтрации трейсов по тенанту

УСТОЙЧИВОСТЬ: если OTel не установлен — middleware работает как no-op,
trace_id берётся из contextvars (как в JUGO-032).
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ats.infra.logging.context import get_log_context, set_log_context
from ats.infra.tracing.context import get_current_trace_id, is_tracing_enabled
from ats.infra.tracing.setup import get_tracer

tracer = get_tracer("ats.http")


class TracingMiddleware(BaseHTTPMiddleware):
    """Создаёт OTel span для каждого HTTP-запроса.

    Интегрируется с RequestContextMiddleware:
    - RequestContextMiddleware (внешний) устанавливает request_id/trace_id
    - TracingMiddleware (внутренний) создаёт OTel span и синхронизирует trace_id

    Порядок middleware в FastAPI (выполняется снизу вверх, т.е. последний
    добавленный — самый внешний):
        app.add_middleware(RequestContextMiddleware)  # внешний
        app.add_middleware(TracingMiddleware)          # внутренний

    TracingMiddleware видит trace_id, установленный RequestContextMiddleware.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        method = request.method
        path = request.url.path

        # Извлекаем trace_id из contextvars (установлен RequestContextMiddleware)
        existing_trace_id = get_log_context("trace_id")

        if not is_tracing_enabled():
            # No-op: trace_id уже в contextvars, просто пропускаем
            response = await call_next(request)
            return response

        # Создаём OTel span для HTTP-запроса
        span_name = f"HTTP {method} {path}"

        with tracer.start_as_current_span(span_name) as span:
            # Атрибуты HTTP-спецификации (semconv)
            span.set_attribute("http.method", method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.scheme", request.url.scheme)
            span.set_attribute("http.host", request.url.hostname or "")
            span.set_attribute("http.target", path)
            span.set_attribute("http.flavor", f"{request.url.scheme.upper()}")

            # Если есть trace_id из contextvars — синхронизируем с OTel
            otel_trace_id = get_current_trace_id()
            if otel_trace_id and otel_trace_id != existing_trace_id:
                set_log_context("trace_id", otel_trace_id)

            # tenant_id из contextvars (если уже установлен)
            tenant_id = get_log_context("tenant_id")
            if tenant_id:
                span.set_attribute("tenant.id", tenant_id)

            try:
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_attribute("error", True)
                return response
            except Exception as exc:
                span.set_attribute("error", True)
                span.set_attribute("exception.type", type(exc).__name__)
                span.set_attribute("exception.message", str(exc)[:500])
                span.record_exception(exc)
                raise
