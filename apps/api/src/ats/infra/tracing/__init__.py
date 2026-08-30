"""OpenTelemetry трейсинг (JUGO-030).

Трейсы HTTP→воркер, trace_id во всех слоях, экспорт в Jaeger.
Ленивый импорт OTel SDK: если не установлен — no-op (dev/stub).

- setup_tracing() — инициализация OTel (вызывается в main.py/cli.py)
- TracingMiddleware — span для каждого HTTP-запроса
- get_tracer() — получение tracer (no-op если OTel недоступен)
- capture_trace_context() / restore_trace_context() — прокидывание в воркеры
- get_current_trace_id() — синхронный доступ к trace_id из любого слоя
"""

from ats.infra.tracing.context import (
    extract_trace_context,
    get_current_span_id,
    get_current_trace_id,
    get_trace_context_for_propagation,
    is_tracing_enabled,
)
from ats.infra.tracing.middleware import TracingMiddleware
from ats.infra.tracing.propagation import (
    capture_trace_context,
    restore_trace_context,
    with_trace_context,
)
from ats.infra.tracing.settings import settings as tracing_settings
from ats.infra.tracing.setup import get_tracer, setup_tracing

__all__ = [
    "TracingMiddleware",
    "capture_trace_context",
    "extract_trace_context",
    "get_current_span_id",
    "get_current_trace_id",
    "get_trace_context_for_propagation",
    "get_tracer",
    "is_tracing_enabled",
    "restore_trace_context",
    "setup_tracing",
    "tracing_settings",
    "with_trace_context",
]
