"""Rate limiting middleware (JUGO-191).

Контракт ТЗ §14.2:
    Rate limits per-key и per-user (Redis, sliding window):
    600 rpm чтение, 120 rpm запись; заголовки X-RateLimit-*.

Реализация: sliding window counter (in-memory для dev, Redis-готовый порт).

Заголовки в ответе:
    X-RateLimit-Limit:     лимит запросов в окне
    X-RateLimit-Remaining: оставшиеся запросы
    X-RateLimit-Reset:     Unix-timestamp сброса окна

SECURE FIRST: лимит по tenant_id + API-key/user; deny-by-default при превышении.
УСТОЙЧИВОСТЬ: in-memory fallback; порт для Redis sliding window.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ats.infra.tracing.context import get_current_trace_id

logger = logging.getLogger(__name__)

# Лимиты по ТЗ: 600 rpm чтение, 120 rpm запись
_READ_LIMIT = 600
_WRITE_LIMIT = 120
_WINDOW_SECONDS = 60  # 1 минута

# Методы записи
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class WindowEntry:
    """Счётчик sliding window: timestamps запросов."""

    timestamps: list[float] = field(default_factory=list)

    def add_and_count(self, now: float, window: float, limit: int) -> tuple[int, float]:
        """Добавить запрос, удалить старые, вернуть (count, reset_at)."""
        cutoff = now - window
        self.timestamps = [ts for ts in self.timestamps if ts > cutoff]
        self.timestamps.append(now)
        # reset_at = конец окна самого старого запроса в окне
        reset_at = self.timestamps[0] + window if self.timestamps else now + window
        return len(self.timestamps), reset_at


class RateLimitStore:
    """In-memory sliding window store. Prod -> Redis (ZSET sliding window)."""

    def __init__(self) -> None:
        self._windows: dict[str, WindowEntry] = defaultdict(WindowEntry)

    def check(self, key: str, limit: int, window: float = _WINDOW_SECONDS) -> tuple[int, float]:
        """Проверить и обновить лимит. Возвращает (count, reset_at)."""
        entry = self._windows[key]
        now = time.time()
        return entry.add_and_count(now, window, limit)

    def clear(self) -> None:
        """Очистить все окна (для тестов)."""
        self._windows.clear()


# Singleton для dev-режима
_global_store: RateLimitStore | None = None


def get_rate_limit_store() -> RateLimitStore:
    """Получить глобальный singleton store."""
    global _global_store
    if _global_store is None:
        _global_store = RateLimitStore()
    return _global_store


def reset_rate_limit_store() -> None:
    """Сбросить store (для тестов)."""
    global _global_store
    _global_store = None


def _get_identifier(request: Request) -> str:
    """Извлечь идентификатор для лимитирования: API-key > user > tenant > IP.

    SECURE FIRST: приоритет — наиболее специфичный идентификатор.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key}"

    user_id = request.headers.get("X-User-Id")
    if user_id:
        return f"user:{user_id}"

    tenant_id = request.headers.get("X-Tenant-Id", "default")
    client_host = request.client.host if request.client else "unknown"
    return f"tenant:{tenant_id}:ip:{client_host}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter with X-RateLimit-* headers."""

    def __init__(
        self,
        app: Any,
        read_limit: int = _READ_LIMIT,
        write_limit: int = _WRITE_LIMIT,
    ) -> None:
        super().__init__(app)
        self.read_limit = read_limit
        self.write_limit = write_limit

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        identifier = _get_identifier(request)
        is_write = request.method in _WRITE_METHODS
        limit = self.write_limit if is_write else self.read_limit

        # Ключ: identifier:method_type (read/write)
        rate_key = f"{identifier}:{'write' if is_write else 'read'}"

        store = get_rate_limit_store()
        count, reset_at = store.check(rate_key, limit)

        remaining = max(0, limit - count)

        # Добавляем заголовки ко всем ответам
        def add_headers(response: Response) -> Response:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(int(reset_at))
            return response

        if count > limit:
            logger.warning(
                "Rate limit exceeded: key=%s, count=%d, limit=%d",
                rate_key,
                count,
                limit,
            )
            trace_id = get_current_trace_id() or ""
            problem_response = JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank",
                    "title": "Too Many Requests",
                    "status": 429,
                    "detail": (
                        f"Rate limit exceeded. Retry after {int(reset_at - time.time())} seconds."
                    ),
                    "errors": [],
                    "trace_id": trace_id,
                },
                media_type="application/problem+json",
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset_at)),
                    "Retry-After": str(max(1, int(reset_at - time.time()))),
                },
            )
            return problem_response

        response = await call_next(request)
        return add_headers(response)
