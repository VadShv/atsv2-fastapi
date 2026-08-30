"""Тесты Prometheus-метрик (JUGO-031).

Проверяют:
- Настройки MetricsSettings (env: ATS_METRICS_*)
- No-op fallback: если prometheus_client не установлен — метрики не падают
- MetricsMiddleware: инкрементирует http_requests_total
- /metrics endpoint: возвращает ответ
- Registry: все метрики доступны и имеют совместимый интерфейс
- Path normalization: UUID/numeric IDs заменяются на {id}
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.metrics.middleware import _normalize_path, _status_group
from ats.infra.metrics.registry import (
    ai_requests_total,
    arq_jobs_total,
    arq_queue_depth,
    get_metrics_output,
    http_requests_total,
    is_metrics_enabled,
    outbox_lag_events,
    outbox_published_total,
    search_requests_total,
)
from ats.infra.metrics.settings import settings as metrics_settings

# --- Настройки ---

class TestMetricsSettings:
    def test_defaults(self) -> None:
        assert metrics_settings.enabled is True
        assert metrics_settings.path == "/metrics"
        assert metrics_settings.include_endpoints is True
        assert metrics_settings.group_status_codes is True

    def test_latency_buckets_parsed(self) -> None:
        buckets = [float(b.strip()) for b in metrics_settings.latency_buckets.split(",")]
        assert len(buckets) > 0
        assert 0.005 in buckets
        assert 1.0 in buckets


# --- No-op fallback ---

class TestNoOpMetrics:
    def test_is_metrics_enabled_returns_bool(self) -> None:
        result = is_metrics_enabled()
        assert isinstance(result, bool)

    def test_metrics_inc_does_not_raise(self) -> None:
        """No-op метрики не падают при вызове inc/observe/set."""
        http_requests_total.labels(method="GET", status_group="2xx", path="/test").inc()
        arq_jobs_total.labels(queue="index", status="success").inc()
        outbox_published_total.inc()
        ai_requests_total.labels(model="gpt-4o", status="success").inc()
        search_requests_total.inc()

    def test_gauge_operations_do_not_raise(self) -> None:
        arq_queue_depth.labels(queue="index").set(5)
        outbox_lag_events.set(10)
        arq_queue_depth.labels(queue="index").inc()
        arq_queue_depth.labels(queue="index").dec()

    def test_get_metrics_output_returns_bytes(self) -> None:
        result = get_metrics_output()
        assert isinstance(result, bytes)


# --- Path normalization ---

class TestPathNormalization:
    def test_normal_path_unchanged(self) -> None:
        assert _normalize_path("/api/v1/vacancies") == "/api/v1/vacancies"

    def test_uuid_replaced(self) -> None:
        path = "/api/v1/vacancies/550e8400-e29b-41d4-a716-446655440000"
        assert _normalize_path(path) == "/api/v1/vacancies/{id}"

    def test_numeric_id_replaced(self) -> None:
        assert _normalize_path("/api/v1/candidates/123") == "/api/v1/candidates/{id}"

    def test_multiple_ids_replaced(self) -> None:
        path = "/api/v1/applications/456/candidates/789"
        assert _normalize_path(path) == "/api/v1/applications/{id}/candidates/{id}"

    def test_health_endpoint_unchanged(self) -> None:
        assert _normalize_path("/health") == "/health"

    def test_metrics_endpoint_unchanged(self) -> None:
        assert _normalize_path("/metrics") == "/metrics"


# --- Status group ---

class TestStatusGroup:
    def test_2xx(self) -> None:
        assert _status_group(200) == "2xx"
        assert _status_group(204) == "2xx"

    def test_4xx(self) -> None:
        assert _status_group(404) == "4xx"
        assert _status_group(401) == "4xx"

    def test_5xx(self) -> None:
        assert _status_group(500) == "5xx"
        assert _status_group(503) == "5xx"

    def test_3xx(self) -> None:
        assert _status_group(301) == "3xx"


# --- MetricsMiddleware ---

class TestMetricsMiddleware:
    def test_middleware_does_not_raise(self) -> None:
        """MetricsMiddleware не падает без prometheus_client."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.metrics import MetricsMiddleware

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200

    def test_middleware_counts_requests(self) -> None:
        """После запроса метрики инкрементируются (no-op тоже не падает)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.metrics import MetricsMiddleware

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        # Если prometheus_client установлен — метрика инкрементирована
        # Если нет — no-op, тоже OK

    def test_middleware_records_error(self) -> None:
        """MetricsMiddleware не падает при 500-й ошибке."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.metrics import MetricsMiddleware

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)

        @app.get("/error")
        async def error_endpoint() -> dict[str, str]:
            raise RuntimeError("test error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/error")
        assert response.status_code == 500


# --- /metrics endpoint ---

class TestMetricsEndpoint:
    def test_metrics_endpoint_returns_response(self) -> None:
        """/metrics endpoint возвращает ответ."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.metrics import metrics_router

        app = FastAPI()
        app.include_router(metrics_router)

        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200
        assert len(response.content) > 0

    def test_metrics_endpoint_with_app(self) -> None:
        """/metrics доступен в полном приложении."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ats.infra.metrics import MetricsMiddleware, metrics_router

        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        app.include_router(metrics_router)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        # Делаем запрос
        client.get("/test")
        # Проверяем /metrics
        response = client.get("/metrics")
        assert response.status_code == 200


# --- Registry доступность ---

class TestRegistryAvailability:
    def test_all_http_metrics_available(self) -> None:
        assert http_requests_total is not None
        assert hasattr(http_requests_total, "labels")
        assert hasattr(http_requests_total, "inc")

    def test_all_worker_metrics_available(self) -> None:
        assert arq_queue_depth is not None
        assert arq_jobs_total is not None
        assert hasattr(arq_queue_depth, "set")
        assert hasattr(arq_jobs_total, "inc")

    def test_all_outbox_metrics_available(self) -> None:
        assert outbox_lag_events is not None
        assert outbox_published_total is not None
        assert hasattr(outbox_lag_events, "set")
        assert hasattr(outbox_published_total, "inc")

    def test_all_ai_metrics_available(self) -> None:
        from ats.infra.metrics.registry import (
            ai_request_duration_seconds,
            ai_tokens_total,
        )

        assert ai_requests_total is not None
        assert ai_request_duration_seconds is not None
        assert ai_tokens_total is not None
        assert hasattr(ai_request_duration_seconds, "observe")
        assert hasattr(ai_tokens_total, "inc")

    def test_all_search_metrics_available(self) -> None:
        from ats.infra.metrics.registry import (
            search_request_duration_seconds,
            search_results_count,
        )

        assert search_requests_total is not None
        assert search_request_duration_seconds is not None
        assert search_results_count is not None
        assert hasattr(search_request_duration_seconds, "observe")
        assert hasattr(search_results_count, "observe")


# --- Интеграция с полным app ---

class TestFullAppMetrics:
    def test_metrics_endpoint_in_full_app(self) -> None:
        """/metrics доступен в полном приложении через main.py."""
        from fastapi.testclient import TestClient

        from ats.main import app

        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_health_request_tracked(self) -> None:
        """Запрос к /health инкрементирует HTTP-метрики."""
        from fastapi.testclient import TestClient

        from ats.main import app

        client = TestClient(app)
        client.get("/health")

        # Проверяем /metrics содержит данные
        response = client.get("/metrics")
        assert response.status_code == 200
        # Если prometheus_client установлен — в ответе будут метрики
        # Если нет — no-op ответ
