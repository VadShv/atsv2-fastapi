"""Реестр метрик Prometheus (JUGO-031).

WHITEBOX AI: метрики AI-операций (model, tokens, latency) — для прозрачности.
БЫСТРЕЙШИЙ ПОИСК: метрики поиска (latency, results_count) — для мониторинга.
УСТОЙЧИВОСТЬ: если prometheus_client не установлен — no-op метрики.

Метрики:
    HTTP:
      - http_requests_total{method, status_group, path} — Counter
      - http_request_duration_seconds{method, status_group, path} — Histogram
      - http_requests_in_progress — Gauge
    Workers (arq):
      - arq_queue_depth{queue} — Gauge
      - arq_jobs_total{queue, status} — Counter
      - arq_job_duration_seconds{queue} — Histogram
    Outbox:
      - outbox_lag_events — Gauge (количество необработанных событий)
      - outbox_published_total — Counter
      - outbox_failed_total — Counter (неудачные публикации в Stream)
      - outbox_lag_seconds — Gauge (лаг: now - occurred_at самого старого)
    AI:
      - ai_requests_total{model, status} — Counter
      - ai_request_duration_seconds{model} — Histogram
      - ai_tokens_total{model, type} — Counter (prompt/completion)
    Search:
      - search_requests_total — Counter
      - search_request_duration_seconds — Histogram
      - search_results_count — Histogram
"""

from __future__ import annotations

from typing import Any

from ats.infra.metrics.settings import settings as metrics_settings

_HAS_PROMETHEUS = False
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest

    _HAS_PROMETHEUS = True
except ImportError:
    Counter = None  # type: ignore[assignment]
    Gauge = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]


class _NoOpMetric:
    """No-op метрика — совместимый интерфейс, ничего не делает."""

    def labels(self, **kwargs: Any) -> _NoOpMetric:
        return self

    def inc(self, amount: float = 1) -> None:
        pass

    def dec(self, amount: float = 1) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def observe(self, amount: float) -> None:
        pass


# --- HTTP metrics ---

http_requests_total: Any
http_request_duration_seconds: Any
http_requests_in_progress: Any

# --- Worker metrics ---

arq_queue_depth: Any
arq_jobs_total: Any
arq_job_duration_seconds: Any

# --- Outbox metrics ---

outbox_lag_events: Any
outbox_published_total: Any

outbox_failed_total: Any
outbox_lag_seconds: Any

# --- AI metrics ---

ai_requests_total: Any
ai_request_duration_seconds: Any
ai_tokens_total: Any

# --- Search metrics ---

search_requests_total: Any
search_request_duration_seconds: Any
search_results_count: Any


def _init_metrics() -> None:
    """Инициализировать все метрики. Вызывается при импорте модуля."""
    global http_requests_total, http_request_duration_seconds, http_requests_in_progress
    global arq_queue_depth, arq_jobs_total, arq_job_duration_seconds
    global outbox_lag_events, outbox_published_total
    global outbox_failed_total, outbox_lag_seconds
    global ai_requests_total, ai_request_duration_seconds, ai_tokens_total
    global search_requests_total, search_request_duration_seconds, search_results_count

    if not _HAS_PROMETHEUS:
        no_op = _NoOpMetric()
        http_requests_total = no_op
        http_request_duration_seconds = no_op
        http_requests_in_progress = no_op
        arq_queue_depth = no_op
        arq_jobs_total = no_op
        arq_job_duration_seconds = no_op
        outbox_lag_events = no_op
        outbox_published_total = no_op
        outbox_failed_total = no_op
        outbox_lag_seconds = no_op
        ai_requests_total = no_op
        ai_request_duration_seconds = no_op
        ai_tokens_total = no_op
        search_requests_total = no_op
        search_request_duration_seconds = no_op
        search_results_count = no_op
        return

    assert Counter is not None
    assert Gauge is not None
    assert Histogram is not None

    # HTTP
    http_requests_total = Counter(
        "ats_http_requests_total",
        "Total HTTP requests",
        ["method", "status_group", "path"],
    )
    http_request_duration_seconds = Histogram(
        "ats_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "status_group", "path"],
        buckets=_parse_buckets(),
    )
    http_requests_in_progress = Gauge(
        "ats_http_requests_in_progress",
        "HTTP requests currently in progress",
    )

    # Workers
    arq_queue_depth = Gauge(
        "ats_arq_queue_depth",
        "arq queue depth (pending jobs)",
        ["queue"],
    )
    arq_jobs_total = Counter(
        "ats_arq_jobs_total",
        "Total arq jobs processed",
        ["queue", "status"],
    )
    arq_job_duration_seconds = Histogram(
        "ats_arq_job_duration_seconds",
        "arq job processing duration",
        ["queue"],
        buckets=_parse_buckets(),
    )

    # Outbox
    outbox_lag_events = Gauge(
        "ats_outbox_lag_events",
        "Unprocessed outbox events count",
    )
    outbox_published_total = Counter(
        "ats_outbox_published_total",
        "Total outbox events published",
    )
    outbox_failed_total = Counter(
        "ats_outbox_failed_total",
        "Total outbox events failed to publish",
    )
    outbox_lag_seconds = Gauge(
        "ats_outbox_lag_seconds",
        "Outbox lag in seconds (now - oldest unprocessed occurred_at)",
    )

    # AI
    ai_requests_total = Counter(
        "ats_ai_requests_total",
        "Total AI API requests",
        ["model", "status"],
    )
    ai_request_duration_seconds = Histogram(
        "ats_ai_request_duration_seconds",
        "AI API request latency",
        ["model"],
        buckets=_parse_buckets(),
    )
    ai_tokens_total = Counter(
        "ats_ai_tokens_total",
        "Total AI tokens used",
        ["model", "type"],
    )

    # Search
    search_requests_total = Counter(
        "ats_search_requests_total",
        "Total search requests",
    )
    search_request_duration_seconds = Histogram(
        "ats_search_request_duration_seconds",
        "Search request latency",
        buckets=_parse_buckets(),
    )
    search_results_count = Histogram(
        "ats_search_results_count",
        "Number of search results returned",
        buckets=[0, 1, 5, 10, 25, 50, 100, 250, 500, 1000],
    )


def _parse_buckets() -> list[float]:
    """Парсить buckets из настроек (CSV строка)."""
    try:
        return [float(b.strip()) for b in metrics_settings.latency_buckets.split(",")]
    except (ValueError, AttributeError):
        return [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]


def is_metrics_enabled() -> bool:
    """Проверить, доступен ли prometheus_client."""
    return _HAS_PROMETHEUS


def get_metrics_output() -> bytes:
    """Получить метрики в формате Prometheus exposition.

    Возвращает b"" если prometheus_client не установлен.
    """
    if not _HAS_PROMETHEUS or generate_latest is None:
        return b""
    return generate_latest()


# Инициализация при импорте
_init_metrics()
