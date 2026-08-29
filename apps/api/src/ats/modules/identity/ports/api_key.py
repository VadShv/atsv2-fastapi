"""Порт ApiKeyStore (SECURE FIRST, ТЗ §15).

Хранение API-ключей (только хэши) + поиск по хэшу.
Домен зависит от интерфейса; реализация (Postgres / in-memory) — в infra.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.identity.domain.api_key import ApiKey, ApiKeyCreateResult, ApiKeyInfo


@runtime_checkable
class ApiKeyStore(Protocol):
    """Порт: хранение и управление API-ключами."""

    async def create_key(
        self,
        tenant_id: UUID,
        name: str,
        scopes: frozenset[str],
        created_by: UUID | None = None,
    ) -> ApiKeyCreateResult:
        """Создать API-ключ. Возвращает raw_key (один раз!) + метаданные."""
        ...

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Найти ключ по хэшу (для middleware auth). None — не найден."""
        ...

    async def get_by_id(self, key_id: UUID) -> ApiKey | None:
        """Найти ключ по ID (для управления)."""
        ...

    async def list_keys(self, tenant_id: UUID) -> list[ApiKeyInfo]:
        """Список ключей тенанта (без raw_key и без hash)."""
        ...

    async def revoke_key(self, key_id: UUID) -> bool:
        """Отозвать ключ. True — успешно, False — не найден."""
        ...

    async def update_last_used(self, key_id: UUID) -> None:
        """Обновить время последнего использования (для аналитики)."""
        ...
