"""Router для /metrics endpoint (JUGO-031).

SCURA FIRST: endpoint без аутентификации, но содержит только агрегированные
метрики (без ПД). В продакшене рекомендуется защитить через mTLS или IP allowlist.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from ats.infra.metrics.registry import get_metrics_output, is_metrics_enabled
from ats.infra.metrics.settings import settings as metrics_settings

router = APIRouter(tags=["system"])


@router.get(
    metrics_settings.path,
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def metrics() -> Response:
    """Prometheus scrape endpoint.

    Возвращает метрики в формате Prometheus exposition.
    Если prometheus_client не установлен — возвращает пустой ответ.
    """
    if not is_metrics_enabled():
        return PlainTextResponse(
            content="# prometheus_client not installed\n",
            media_type="text/plain",
        )
    return Response(
        content=get_metrics_output(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
