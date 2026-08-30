"""Idempotency-Key middleware (JUGO-190).

Контракт ТЗ §14.2:
    Idempotency-Key на всех POST, создающих сущности; хранение 24 ч.

Если POST-запрос содержит заголовок `Idempotency-Key`, ответ кэшируется на 24 часа.
Повторный запрос с тем же ключом возвращает сохранённый ответ (статус, тело, заголовки).

SECURE FIRST: ключи изолированы по tenant_id (через X-Tenant-Id или из сессии).
УСТОЙЧИВОСТЬ: In-memory store для dev; порт IdempotencyStore для Redis/DB.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# TTL по ТЗ: 24 часа
_IDEMPOTENCY_TTL_SECONDS = 86400

# Только POST создаёт сущности → идемпотентность
_IDEMPOTENT_METHODS = {"POST"}


@dataclass(frozen=True)
class CachedResponse:
    """Кэшированный ответ идемпотентного запроса."""

    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    cached_at: float = field(default_factory=time.time)


class IdempotencyStore:
    """Порт для хранения идемпотентных ответов.

    In-memory реализация для dev; prod → Redis (см. RedisIdempotencyStore).
    """

    def __init__(self) -> None:
        self._store: dict[str, CachedResponse] = {}

    def get(self, key: str) -> CachedResponse | None:
        """Получить кэшированный ответ, если не истёк TTL."""
        cached = self._store.get(key)
        if cached is None:
            return None
        if time.time() - cached.cached_at > _IDEMPOTENCY_TTL_SECONDS:
            del self._store[key]
            return None
        return cached

    def set(self, key: str, response: CachedResponse) -> None:
        """Сохранить ответ."""
        self._store[key] = response

    def clear(self) -> None:
        """Очистить все кэшированные ответы (для тестов)."""
        self._store.clear()

    def cleanup_expired(self) -> int:
        """Удалить истёкшие записи. Возвращает количество удалённых."""
        now = time.time()
        expired = [
            key
            for key, cached in self._store.items()
            if now - cached.cached_at > _IDEMPOTENCY_TTL_SECONDS
        ]
        for key in expired:
            del self._store[key]
        return len(expired)

    def find_conflict(self, conflict_prefix: str, current_cache_key: str) -> CachedResponse | None:
        """Найти кэшированный ответ с тем же Idempotency-Key, но другим телом.

        Возвращает конфликтующий CachedResponse или None.
        """
        for existing_key, cached in self._store.items():
            if existing_key.startswith(conflict_prefix) and existing_key != current_cache_key:
                return cached
        return None


# Singleton для dev-режима
_global_store: IdempotencyStore | None = None


def get_idempotency_store() -> IdempotencyStore:
    """Получить глобальный singleton store (для middleware без DI)."""
    global _global_store
    if _global_store is None:
        _global_store = IdempotencyStore()
    return _global_store


def reset_idempotency_store() -> None:
    """Сбросить store (для тестов)."""
    global _global_store
    _global_store = None


def _make_key(tenant_id: str, method: str, path: str, idempotency_key: str, body: bytes) -> str:
    """Составной ключ: tenant + method + path + idempotency-key + body-hash.

    SECURE FIRST: body-hash гарантирует, что один ключ с другим телом → 422.
    Это предотвращает подмену данных между запросами с одним ключом.
    """
    body_hash = hashlib.sha256(body).hexdigest()[:16]
    return f"{tenant_id}:{method}:{path}:{idempotency_key}:{body_hash}"


def _get_tenant_id(request: Request) -> str:
    """Извлечь tenant_id из заголовков (X-Tenant-Id) или default."""
    return request.headers.get("X-Tenant-Id", "default")


def _conflict_response() -> JSONResponse:
    """Построить 422 problem+json ответ для конфликта Idempotency-Key.

    Возвращается напрямую из middleware, т.к. ProblemException, брошенный
    из BaseHTTPMiddleware.dispatch, не перехватывается exception handlers.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "type": "about:blank",
            "title": "Idempotency Key Conflict",
            "status": 422,
            "detail": (
                "Idempotency-Key already used for a request with a different body. "
                "Use a new Idempotency-Key for a different request body."
            ),
            "errors": [],
            "trace_id": "",
        },
        media_type="application/problem+json",
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware для обработки Idempotency-Key на POST-запросах.

    Если заголовок Idempotency-Key присутствует:
    1. Вычисляется составной ключ (tenant + path + body-hash).
    2. Если ключ найден в store → возвращается кэшированный ответ.
    3. Если тело не совпадает с сохранённым (другой body-hash) → 422.
    4. Иначе запрос выполняется, ответ кэшируется.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key or request.method not in _IDEMPOTENT_METHODS:
            return await call_next(request)

        # Читаем тело запроса (нужно для body-hash)
        body = await request.body()

        tenant_id = _get_tenant_id(request)
        cache_key = _make_key(tenant_id, request.method, request.url.path, idempotency_key, body)

        store = get_idempotency_store()

        # Проверяем конфликт: тот же Idempotency-Key, но другое тело
        conflict_prefix = f"{tenant_id}:{request.method}:{request.url.path}:{idempotency_key}"
        conflict = store.find_conflict(conflict_prefix, cache_key)
        if conflict is not None:
            logger.warning("Idempotency conflict: key=%s, tenant=%s", idempotency_key, tenant_id)
            return _conflict_response()

        # Проверяем кэш
        cached = store.get(cache_key)
        if cached is not None:
            logger.debug("Idempotency hit: key=%s, status=%d", idempotency_key, cached.status_code)
            return Response(
                content=cached.body,
                status_code=cached.status_code,
                headers={**cached.headers, "X-Idempotent-Replay": "true"},
                media_type=cached.headers.get("content-type"),
            )

        # Восстанавливаем тело для downstream (body уже прочитан)
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive  # type: ignore[method-assign]

        response = await call_next(request)

        # Кэшируем только успешные (2xx) и 422 ответы (ошибка валидации тоже идемпотентна)
        if 200 <= response.status_code < 300 or response.status_code == 422:
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk

            cached_response = CachedResponse(
                status_code=response.status_code,
                body=response_body,
                headers=dict(response.headers),
            )
            store.set(cache_key, cached_response)

            # Возвращаем новый Response (так как body_iterator уже потреблён)
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response
