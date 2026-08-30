"""Prometheus-метрики (JUGO-031).

RPS, latency, queue depth, outbox lag, AI metrics, search metrics.
Ленивый импорт prometheus_client: если не установлен — no-op.

- MetricsMiddleware — автоматический сбор HTTP-метрик
- router — /metrics endpoint для scrape
- registry — все метрики (Counter/Gauge/Histogram)
- settings — ATS_METRICS_* env vars
"""

from ats.infra.metrics.middleware import MetricsMiddleware
from ats.infra.metrics.registry import (
    ai_request_duration_seconds,
    ai_requests_total,
    ai_tokens_total,
    arq_job_duration_seconds,
    arq_jobs_total,
    arq_queue_depth,
    get_metrics_output,
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
    is_metrics_enabled,
    outbox_lag_events,
    outbox_published_total,
    search_request_duration_seconds,
    search_requests_total,
    search_results_count,
)
from ats.infra.metrics.router import router as metrics_router
from ats.infra.metrics.settings import settings as metrics_settings

__all__ = [
    "MetricsMiddleware",
    "ai_request_duration_seconds",
    "ai_requests_total",
    "ai_tokens_total",
    "arq_job_duration_seconds",
    "arq_jobs_total",
    "arq_queue_depth",
    "get_metrics_output",
    "http_request_duration_seconds",
    "http_requests_in_progress",
    "http_requests_total",
    "is_metrics_enabled",
    "metrics_router",
    "metrics_settings",
    "outbox_lag_events",
    "outbox_published_total",
    "search_request_duration_seconds",
    "search_requests_total",
    "search_results_count",
]
