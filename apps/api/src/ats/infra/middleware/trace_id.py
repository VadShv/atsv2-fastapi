"""Trace-ID middleware (JUGO-190): сквозной trace_id в ответах.

Контракт ТЗ §14.3: trace_id в каждой проблеме (problem+json) и в заголовках.

Если входящий запрос содержит X-Trace-Id (или W3C traceparent), используется он.
Иначе генерируется новый trace_id. В ответ всегда добавляется X-Trace-Id.

УСТОЙЧИВОСТЬ: trace_id синхронизируется с contextvars (логи, аудит, метрики).
"""

from __future__ import annotations

import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ats.infra.logging.context import set_log_context


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Добавляет сквозной trace_id в каждый запрос/ответ.

    1. Принимает X-Trace-Id от клиента (если есть).
    2. Иначе генерирует новый UUID.
    3. Устанавливает в contextvars (логи, аудит).
    4. Добавляет X-Trace-Id в ответ.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        trace_id = request.headers.get("X-Trace-Id")
        if not trace_id:
            # Проверяем W3C traceparent
            traceparent = request.headers.get("traceparent", "")
            if traceparent:
                parts = traceparent.split("-")
                if len(parts) >= 3 and len(parts[1]) == 32:
                    trace_id = parts[1]
            if not trace_id:
                trace_id = uuid.uuid4().hex

        # Устанавливаем в contextvars (для логов/аудита/метрик)
        set_log_context("trace_id", trace_id)

        response = await call_next(request)

        # Добавляем в ответ
        response.headers["X-Trace-Id"] = trace_id
        return response
