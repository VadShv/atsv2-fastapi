"""Вспомогательные функции для работы с trace_id и span context.

УСТОЙЧИВОСТЬ: если OTel не установлен — функции возвращают пустые значения,
не падая. Это позволяет доменному коду вызывать get_current_trace_id()
без условных импортов.

БЫСТРЕЙШИЙ ПОИСК: trace_id доступен синхронно из contextvars (без I/O).
"""

from __future__ import annotations

from typing import Any

from ats.infra.logging.context import get_log_context, set_log_context

# Флаг доступности OTel SDK
try:
    from opentelemetry import trace as _otel_trace

    _HAS_OTEL = True
except ImportError:
    _otel_trace = None  # type: ignore[assignment]
    _HAS_OTEL = False


def get_current_trace_id() -> str | None:
    """Получить текущий trace_id из OTel span или contextvars.

    Возвращает hex-строку (32 символа) или None, если трейс не активен.
    Сначала проверяет OTel span, затем fallback на contextvars (trace_id).
    """
    if _HAS_OTEL:
        span = _otel_trace.get_current_span()  # type: ignore[union-attr]
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            trace_id = format(ctx.trace_id, "032x")
            # Синхронизируем с contextvars (для логов/аудита)
            set_log_context("trace_id", trace_id)
            return trace_id

    # Fallback: contextvars (установлен middleware'ом)
    return get_log_context("trace_id")


def get_current_span_id() -> str | None:
    """Получить текущий span_id из OTel span."""
    if not _HAS_OTEL:
        return None

    span = _otel_trace.get_current_span()  # type: ignore[union-attr]
    ctx = span.get_span_context()
    if ctx and ctx.is_valid:
        return format(ctx.span_id, "016x")
    return None


def is_tracing_enabled() -> bool:
    """Проверить, доступен ли OTel SDK."""
    return _HAS_OTEL


def get_trace_context_for_propagation() -> dict[str, str]:
    """Получить заголовки W3C traceparent для прокидывания в воркеры.

    Возвращает dict с заголовком 'traceparent' (W3C Trace Context).
    Если OTel не установлен или нет активного span — возвращает пустой dict.
    """
    if not _HAS_OTEL:
        # Fallback: прокидываем trace_id из contextvars как кастомный заголовок
        trace_id = get_log_context("trace_id")
        if trace_id:
            return {"x-trace-id": trace_id}
        return {}

    try:
        from opentelemetry.propagate import inject

        headers: dict[str, str] = {}
        inject(headers)
        # Fallback: always include x-trace-id from contextvars
        # so that restore works even without an active OTel span
        if "x-trace-id" not in headers:
            trace_id = get_log_context("trace_id")
            if trace_id:
                headers["x-trace-id"] = trace_id
        return headers
    except Exception:
        return {}


def extract_trace_context(headers: dict[str, Any]) -> str | None:
    """Извлечь trace_id из заголовков (для воркеров: восстановить контекст).

    Возвращает trace_id или None.
    """
    if _HAS_OTEL:
        try:
            from opentelemetry.propagate import extract

            # Пробуем извлечь через OTel propagator
            ctx = extract(headers)
            span = _otel_trace.get_current_span(ctx)  # type: ignore[union-attr]
            span_ctx = span.get_span_context()
            if span_ctx and span_ctx.is_valid:
                return format(span_ctx.trace_id, "032x")
        except Exception:
            pass

    # Fallback: кастомный заголовок
    return headers.get("x-trace-id") or headers.get("X-Trace-Id")
