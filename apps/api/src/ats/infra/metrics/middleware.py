"""Middleware для сбора HTTP-метрик Prometheus (JUGO-031).

Автоматически собирает:
- http_requests_total{method, status_group, path} — Counter
- http_request_duration_seconds{method, status_group, path} — Histogram
- http_requests_in_progress — Gauge

УСТОЙЧИВОСТЬ: если prometheus_client не установлен — no-op middleware.
БЫСТРЕЙШИЙ ПОИСК: latency-метрики помогают выявить медленные endpoints.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ats.infra.metrics.registry import (
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
    is_metrics_enabled,
    metrics_settings,
)


def _status_group(status_code: int) -> str:
    """Группировать status code: 2xx, 4xx, 5xx и т.д."""
    if metrics_settings.group_status_codes:
        return f"{status_code // 100}xx"
    return str(status_code)


def _normalize_path(path: str) -> str:
    """Нормализовать путь: заменить ID на {id} для cardinality control.

    /api/v1/vacancies/550e8400-e29b-41d4-a716-446655440000 → /api/v1/vacancies/{id}
    /api/v1/candidates/123 → /api/v1/candidates/{id}

    SECURE FIRST: предотвращает cardinality explosion (и утечку ID в метриках).
    """
    import re

    # UUID
    path = re.sub(
        r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "/{id}",
        path,
        flags=re.IGNORECASE,
    )
    # Numeric IDs
    path = re.sub(r"/\d+", "/{id}", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Собирает Prometheus-метрики для каждого HTTP-запроса."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not is_metrics_enabled():
            return await call_next(request)

        method = request.method
        path = _normalize_path(request.url.path)

        http_requests_in_progress.inc()
        start = time.monotonic()

        try:
            response = await call_next(request)
            duration = time.monotonic() - start

            status_group = _status_group(response.status_code)

            http_requests_total.labels(
                method=method,
                status_group=status_group,
                path=path,
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                status_group=status_group,
                path=path,
            ).observe(duration)

            return response
        except Exception:
            duration = time.monotonic() - start
            http_requests_total.labels(
                method=method,
                status_group="5xx",
                path=path,
            ).inc()
            http_request_duration_seconds.labels(
                method=method,
                status_group="5xx",
                path=path,
            ).observe(duration)
            raise
        finally:
            http_requests_in_progress.dec()
