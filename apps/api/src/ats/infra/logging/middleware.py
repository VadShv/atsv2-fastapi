"""Middleware для логирования: request_id, trace_id, tenant_id в contextvars.

Каждый HTTP-запрос получает уникальный request_id (если нет в заголовке).
trace_id прокидывается из заголовка X-Trace-Id или генерируется.
tenant_id устанавливается после аутентификации.
"""

from __future__ import annotations

import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ats.infra.logging.context import set_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Устанавливает request_id и trace_id в contextvars для каждого запроса."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())

        set_context(request_id=request_id, trace_id=trace_id)

        response = await call_next(request)

        # Прокинуть ID в заголовки ответа (для корреляции клиентом)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id

        return response
