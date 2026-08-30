"""Redis-реализация семантического кэша AI-запросов.

Кэширует по детерминированному ключу (prompt+variables+model) для temperature==0.
Ускоряет отклик и снижает стоимость LLM-вызовов.
В dev/stub-режиме — noop (возвращает None), если Redis недоступен.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from ats.infra.ai.cache import CacheStore
from ats.infra.ai.settings import settings as ai_settings

logger = logging.getLogger(__name__)


class RedisCacheStore(CacheStore):
    """Redis-backed cache для AI-вызовов.

    Ленивая инициализация: создаёт Redis-клиент при первом обращении.
    Если Redis недоступен — деградирует в noop (возвращает None из get).
    """

    def __init__(self) -> None:
        self._client: Any | None = None
        self._initialized = False

    async def _ensure_client(self) -> Any | None:
        """Ленивая инициализация Redis-клиента."""
        if self._initialized:
            return self._client
        self._initialized = True
        if not ai_settings.cache_enabled:
            logger.debug("AI cache disabled by settings")
            return None
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            from ats.infra.workers.settings import settings as redis_settings

            self._client = aioredis.from_url(
                redis_settings.url,
                decode_responses=True,
                health_check_interval=30,
            )
            await self._client.ping()
            logger.info("AI Redis cache connected: %s", redis_settings.url)
        except ImportError:
            logger.warning("redis package not installed — AI cache running in noop mode")
            self._client = None
        except Exception as exc:
            logger.warning("AI Redis cache unavailable (%s) — noop mode", exc)
            self._client = None
        return self._client

    async def get(self, key: str) -> str | None:
        client = await self._ensure_client()
        if client is None:
            return None
        try:
            return await client.get(key)
        except Exception as exc:
            logger.warning("AI cache get failed for %s: %s", key, exc)
            return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        client = await self._ensure_client()
        if client is None:
            return
        try:
            await client.set(key, value, ex=ttl_seconds)
        except Exception as exc:
            logger.warning("AI cache set failed for %s: %s", key, exc)

    async def delete(self, key: str) -> None:
        client = await self._ensure_client()
        if client is None:
            return
        try:
            await client.delete(key)
        except Exception as exc:
            logger.warning("AI cache delete failed for %s: %s", key, exc)

    async def close(self) -> None:
        """Закрыть соединение при shutdown."""
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
        self._client = None
        self._initialized = False
