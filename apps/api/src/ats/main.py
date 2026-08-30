"""Точка входа FastAPI-приложения ATS Core.

Запуск: uvicorn ats.main:app --reload
Dev-режим (без БД/LLM): ATS_STUB_MODE=1
"""

from __future__ import annotations

from fastapi import FastAPI

from ats.infra.logging import RequestContextMiddleware, setup_logging
from ats.infra.metrics import MetricsMiddleware, metrics_router
from ats.infra.middleware import (
    IdempotencyMiddleware,
    RateLimitMiddleware,
    TraceIdMiddleware,
    register_problem_handlers,
)
from ats.infra.sentry import SentryMiddleware, setup_sentry
from ats.infra.tracing import TracingMiddleware, setup_tracing
from ats.modules.ai_core.api.embeddings_router import router as embeddings_router
from ats.modules.ai_core.api.prompts_router import router as prompts_router
from ats.modules.ai_core.api.router import router as ai_router
from ats.modules.ai_core.api.skills_router import router as skills_router
from ats.modules.candidates.api.dedup_router import router as dedup_router
from ats.modules.candidates.api.router import router as candidates_router
from ats.modules.events.api.router import router as events_router
from ats.modules.funnel.api.router import router as funnel_router
from ats.modules.identity.api.router import router as auth_router
from ats.modules.identity.infra.csrf import CSRFMiddleware
from ats.modules.m1_screening.api.router import router as screening_router
from ats.modules.organization.api.router import router as org_router
from ats.modules.recruitment.api.applications_router import (
    router as applications_router,
)
from ats.modules.recruitment.api.router import router as recruitment_router
from ats.modules.search.api.router import router as search_router
from ats.modules.webhooks.api.router import router as webhooks_router

# Структурные JSON-логи с маскированием ПД (JUGO-032)
setup_logging()
# OpenTelemetry трейсинг (JUGO-030) — no-op если OTel не установлен
setup_tracing()
# Sentry + алерты (JUGO-034) — no-op если sentry-sdk не установлен
setup_sentry()
logger = __import__("ats.infra.logging", fromlist=["get_logger"]).get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ATS Jugo API",
        description=(
            "AI-native Applicant Tracking System.\n\n"
            "## Authentication\n"
            "- **Web UI**: Session cookie + CSRF (HttpOnly)\n"
            "- **API keys**: `X-API-Key` header with scoped keys\n\n"
            "## Idempotency\n"
            "POST requests accept `Idempotency-Key` header for safe retries (24h TTL).\n\n"
            "## Rate Limiting\n"
            "Sliding window: 600 rpm read, 120 rpm write. Headers: `X-RateLimit-*`.\n\n"
            "## Errors\n"
            "All errors use RFC 9457 (application/problem+json) with `trace_id`.\n\n"
            "## Webhooks\n"
            "Subscribe via `POST /api/v1/webhooks`. "
            "Payloads signed with HMAC-SHA256 (`X-Jugo-Signature`)."
        ),
        version="0.1.0",
        contact={"name": "ATS Jugo", "url": "https://github.com/VadShv/atsv2-fastapi"},
        openapi_tags=[
            {"name": "webhooks", "description": "Webhook subscriptions and delivery journal"},
            {"name": "search", "description": "Hybrid search (BM25 + vector) with boolean queries"},
            {"name": "candidates", "description": "Candidate master profile management"},
            {"name": "recruitment", "description": "Vacancies and requirement sets"},
            {"name": "applications", "description": "Job applications and funnel transitions"},
            {"name": "events", "description": "SSE event stream and event log"},
            {"name": "funnel", "description": "Funnel presets and stage management"},
            {"name": "organization", "description": "Legal entities and org units (tree)"},
        ],
    )

    # Problem+json error handlers (JUGO-190): RFC 9457 для всех ошибок
    register_problem_handlers(app)

    # Middleware: request_id + trace_id в contextvars (JUGO-032)
    app.add_middleware(RequestContextMiddleware)
    # Middleware: Idempotency-Key на POST (JUGO-190)
    app.add_middleware(IdempotencyMiddleware)
    # Middleware: Rate limiting sliding window + X-RateLimit-* (JUGO-191)
    app.add_middleware(RateLimitMiddleware)
    # Middleware: сквозной trace_id в ответах (JUGO-190)
    app.add_middleware(TraceIdMiddleware)
    # Middleware: OTel span для каждого HTTP-запроса (JUGO-030)
    app.add_middleware(TracingMiddleware)
    # Middleware: Prometheus HTTP-метрики (JUGO-031)
    app.add_middleware(MetricsMiddleware)
    # Middleware: Sentry + алерты (JUGO-034)
    app.add_middleware(SentryMiddleware)
    # Middleware: CSRF double-submit cookie (JUGO-021)
    app.add_middleware(CSRFMiddleware)

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(recruitment_router, prefix="/api/v1")
    app.include_router(applications_router, prefix="/api/v1")
    app.include_router(dedup_router, prefix="/api/v1")
    app.include_router(candidates_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")
    app.include_router(funnel_router, prefix="/api/v1")
    app.include_router(webhooks_router, prefix="/api/v1")
    app.include_router(org_router, prefix="/api/v1")
    app.include_router(ai_router, prefix="/api/v1")
    app.include_router(prompts_router, prefix="/api/v1")
    app.include_router(skills_router, prefix="/api/v1")
    app.include_router(embeddings_router, prefix="/api/v1")
    app.include_router(screening_router, prefix="/api/v1")
    # /metrics endpoint (JUGO-031)
    app.include_router(metrics_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    logger.info("ATS Core app initialized")
    return app


app = create_app()
