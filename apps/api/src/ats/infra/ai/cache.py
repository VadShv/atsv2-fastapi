"""Семантический кэш AI-запросов.

Кэширует по хэшу входа (prompt+variables+model) для детерминированных вызовов
(temperature 0). Ускоряет и снижает стоимость. Реализация — Redis (port: CacheStore).
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...


def cache_key(
    prompt_id: str,
    prompt_version: str,
    model: str,
    input_hash: str,
    temperature: float,
) -> str:
    """Детерминированный ключ. Только temperature==0 кэшируется."""
    raw = f"{prompt_id}|{prompt_version}|{model}|{input_hash}|{temperature}"
    return "ai:cache:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
