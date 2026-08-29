"""Middleware для перехвата исключений и отправки в Sentry (JUGO-034).

Перехватывает необработанные 500-е ошибки и отправляет в Sentry + webhook алерт.
УСТОЙЧИВОСТЬ: ошибки в middleware не прерывают запрос (best-effort).
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ats.infra.logging.context import get_log_context
from ats.infra.sentry.alerts import send_alert
from ats.infra.sentry.setup import capture_exception, is_sentry_enabled


class SentryMiddleware(BaseHTTPMiddleware):
    """Перехватывает исключения и отправляет в Sentry + webhook алерт.

    Не перехватывает 4xx (клиентские ошибки) — только 5xx (серверные).
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            # Получить контекст для Sentry
            trace_id = get_log_context("trace_id") or ""
            tenant_id = get_log_context("tenant_id") or ""

            # Отправить в Sentry
            capture_exception(
                exc,
                tags={
                    "http.method": request.method,
                    "http.path": request.url.path,
                    "tenant_id": tenant_id,
                },
                extra={
                    "http.url": str(request.url),
                    "trace_id": trace_id,
                },
                level="error",
            )

            # Отправить webhook алерт
            if is_sentry_enabled() or True:  # алерт отправляется даже без Sentry
                await send_alert(
                    title=f"Unhandled exception: {type(exc).__name__}",
                    message=str(exc)[:500],
                    level="ERROR",
                    trace_id=trace_id,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "tenant_id": tenant_id,
                    },
                )

            raise
