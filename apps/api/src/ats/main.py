"""Точка входа FastAPI-приложения ATS Core.

Запуск: uvicorn ats.main:app --reload
Dev-режим (без БД/LLM): ATS_STUB_MODE=1
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from ats.modules.candidates.api.router import router as candidates_router
from ats.modules.recruitment.api.applications_router import (
    router as applications_router,
)
from ats.modules.recruitment.api.router import router as recruitment_router
from ats.modules.search.api.router import router as search_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ATS Core",
        description="AI-native Applicant Tracking System",
        version="0.1.0",
    )

    app.include_router(recruitment_router, prefix="/api/v1")
    app.include_router(applications_router, prefix="/api/v1")
    app.include_router(candidates_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    logger.info("ATS Core app initialized")
    return app


app = create_app()
