"""CSRF-защита для state-changing requests (SECURE FIRST, ТЗ §15).

Паттерн: double-submit cookie.
- При логине CSRF-токен устанавливается в cookie (ats_csrf, не HttpOnly).
- Для POST/PUT/PATCH/DELETE клиент отправляет тот же токен в заголовке
  X-CSRF-Token.
- Middleware проверяет совпадение cookie и заголовка.

SECURE FIRST: GET/HEAD/OPTIONS — безопасные методы, CSRF не требуется.
Если cookie нет или заголовок не совпадает — 403 Forbidden.
"""

from __future__ import annotations

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "ats_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

# State-changing методы, требующие CSRF-проверку
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Пути, исключённые из CSRF (логин сам устанавливает CSRF-токен)
_EXEMPT_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/health",
    "/metrics",
})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Проверка CSRF-токена для state-changing requests.

    Double-submit cookie pattern:
    1. Cookie ats_csrf содержит CSRF-токен (не HttpOnly — JS может читать).
    2. Для unsafe-методов заголовок X-CSRF-Token должен совпадать с cookie.
    3. Несовпадение → 403 Forbidden.

    SECURE FIRST: stub-режим отключает CSRF для dev (ATS_STUB_MODE=1).
    """

    async def dispatch(self, request: Request, call_next):
        # В stub-режиме CSRF не проверяется (dev-удобство)
        if os.getenv("ATS_STUB_MODE", "1") == "1":
            return await call_next(request)

        method = request.method.upper()

        # Безопасные методы — без проверки
        if method not in _UNSAFE_METHODS:
            return await call_next(request)

        # Исключённые пути
        path = request.url.path
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        # Проверка double-submit
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get(CSRF_HEADER_NAME, "")

        if not cookie_token or not header_token:
            logger.warning(
                "CSRF: missing token (cookie=%s, header=%s) for %s %s",
                bool(cookie_token),
                bool(header_token),
                method,
                path,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF-токен отсутствует"},
            )

        if cookie_token != header_token:
            logger.warning(
                "CSRF: token mismatch for %s %s", method, path
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Недействительный CSRF-токен"},
            )

        return await call_next(request)
