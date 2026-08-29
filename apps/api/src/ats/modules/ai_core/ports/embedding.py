"""Порт: генератор эмбеддингов (часть AI Core).

Эмбеддинги нужны для семантического поиска кандидатов.
Шлюз LLM реализует этот интерфейс; домен зависит от абстракции.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingPort(Protocol):
    """Порт: векторное представление текста."""

    @property
    def dimension(self) -> int:
        """Размерность вектора эмбеддинга."""
        ...

    async def embed(self, tenant_id, text: str) -> list[float]:  # type: ignore[no-untyped-def]
        """Получить вектор эмбеддинга для текста."""
        ...
