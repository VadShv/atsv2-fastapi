"""Прокидывание trace_context между API и воркерами (JUGO-030).

При постановке задачи в очередь (arq) — trace_context сериализуется в заголовки
W3C traceparent и передаётся как часть параметров job.
В воркере — trace_context извлекается и восстанавливается как активный span.

СЦЕНАРИЙ:
    # В API (постановка задачи):
    trace_ctx = capture_trace_context()
    await pool.enqueue_job("my_task", trace_ctx=trace_ctx, ...)

    # В воркере (BaseTask.execute):
    restore_trace_context(params.get("trace_ctx", {}))

УСТОЙЧИВОСТЬ: если OTel не установлен — прокидывается только trace_id
через contextvars (fallback). Воркер всё равно получит trace_id для логов.
"""

from __future__ import annotations

from typing import Any

from ats.infra.logging.context import set_log_context
from ats.infra.tracing.context import (
    extract_trace_context,
    get_trace_context_for_propagation,
    is_tracing_enabled,
)


def capture_trace_context() -> dict[str, str]:
    """Сериализовать текущий trace_context для передачи в воркер.

    Возвращает dict заголовков W3C (traceparent) или fallback {x-trace-id}.
    """
    return get_trace_context_for_propagation()


def restore_trace_context(headers: dict[str, Any] | None) -> str | None:
    """Восстановить trace_context в воркере из заголовков.

    Возвращает восстановленный trace_id или None.
    """
    if not headers:
        return None

    trace_id = extract_trace_context(headers)
    if trace_id:
        set_log_context("trace_id", trace_id)

    if is_tracing_enabled():
        try:
            from opentelemetry import trace
            from opentelemetry.propagate import extract

            ctx = extract(headers)
            token = trace.use_context(ctx)  # type: ignore[union-attr]
            # Токен сохраняется в текущем контексте; не нужно явно detach
            # т.к. контекст воркера изолирован
            return trace_id
        except Exception:
            pass

    return trace_id


def with_trace_context(headers: dict[str, Any] | None):
    """Декоратор/контекст-менеджер для восстановления trace_context в воркере.

    Использование в BaseTask:
        async def execute(self, ctx, **params):
            with with_trace_context(params.get("trace_ctx")):
                ...
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        restore_trace_context(headers)
        yield

    return _ctx()
