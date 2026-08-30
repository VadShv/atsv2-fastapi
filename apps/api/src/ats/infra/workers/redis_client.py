"""Redis-клиент: ленивая инициализация, noop при отсутствии redis-модуля.

В dev/stub-режиме redis может быть не установлен — возвращаем None.
В prod создаём async Redis-клиент для стримов и arq.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from ats.infra.workers.settings import settings as redis_settings

logger = logging.getLogger(__name__)

_client: Any | None = None
_initialized = False


async def get_redis() -> Any | None:
    """Возвращает async Redis-клиент или None (если redis не установлен/noop).

    Ленивая инициализация: создаётся один раз при первом вызове.
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]

        _client = aioredis.from_url(
            redis_settings.url,
            decode_responses=False,
            health_check_interval=redis_settings.health_check_interval,
        )
        await _client.ping()
        logger.info("Redis connected: %s", redis_settings.url)
    except ImportError:
        logger.warning("redis package not installed — running in noop mode")
        _client = None
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — running in noop mode", exc)
        _client = None
    return _client


async def close_redis() -> None:
    """Закрыть соединение с Redis при shutdown."""
    global _client, _initialized
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.aclose()
    _client = None
    _initialized = False
