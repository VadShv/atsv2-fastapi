"""Порт репозитория синонимов поиска (JUGO-172).

Чистый интерфейс, не зависит от инфраструктуры.
Мульти-тенант: все операции scoped по tenant_id.
"""

from __future__ import annotations

from typing import Protocol

from ats.modules.search.domain.synonym import SynonymEntry
from ats.shared.ids import TenantId


class SynonymRepository(Protocol):
    """Репозиторий записей словаря синонимов."""

    async def list_all(self, tenant_id: TenantId) -> list[SynonymEntry]:
        """Получить все записи синонимов тенанта."""
        ...

    async def get(self, tenant_id: TenantId, entry_id: str) -> SynonymEntry | None:
        """Получить запись по ID."""
        ...

    async def find_by_term(self, tenant_id: TenantId, term: str) -> SynonymEntry | None:
        """Найти запись по термиину (case-insensitive)."""
        ...

    async def save(self, entry: SynonymEntry) -> SynonymEntry:
        """Создать или обновить запись (upsert по term)."""
        ...

    async def delete(self, tenant_id: TenantId, entry_id: str) -> bool:
        """Удалить запись. Возвращает True если удалена."""
        ...

    async def get_synonym_map(self, tenant_id: TenantId) -> dict[str, list[str]]:
        """Получить карту {term_lower: [synonym_lowers]} для расширения запросов.

        Используется при поиске: термины запроса расширяются синонимами.
        """
        ...
