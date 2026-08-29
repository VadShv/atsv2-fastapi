"""Точка входа FastAPI-приложения ATS Core.

Запуск: uvicorn ats.main:app --reload
Dev-режим (без БД/LLM): ATS_STUB_MODE=1
"""

from __future__ import annotations

from fastapi import FastAPI

from ats.infra.logging import RequestContextMiddleware, setup_logging
from ats.infra.tracing import TracingMiddleware, setup_tracing
from ats.modules.candidates.api.router import router as candidates_router
from ats.modules.events.api.router import router as events_router
from ats.modules.identity.api.router import router as auth_router
from ats.modules.recruitment.api.applications_router import (
    router as applications_router,
)
from ats.modules.recruitment.api.router import router as recruitment_router
from ats.modules.search.api.router import router as search_router

# Структурные JSON-логи с маскированием ПД (JUGO-032)
setup_logging()
# OpenTelemetry трейсинг (JUGO-030) — no-op если OTel не установлен
setup_tracing()
logger = __import__("ats.infra.logging", fromlist=["get_logger"]).get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ATS Core",
        description="AI-native Applicant Tracking System",
        version="0.1.0",
    )

    # Middleware: request_id + trace_id в contextvars (JUGO-032)
    app.add_middleware(RequestContextMiddleware)
    # Middleware: OTel span для каждого HTTP-запроса (JUGO-030)
    app.add_middleware(TracingMiddleware)

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(recruitment_router, prefix="/api/v1")
    app.include_router(applications_router, prefix="/api/v1")
    app.include_router(candidates_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    logger.info("ATS Core app initialized")
    return app


app = create_app()
