"""In-memory реализация ApiKeyStore для stub/dev-режима (SECURE FIRST).

Хранит API-ключи (хэши) в памяти. Для prod — Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ats.modules.identity.domain.api_key import (
    ApiKey,
    ApiKeyCreateResult,
    ApiKeyInfo,
    generate_api_key,
)
from ats.modules.identity.ports.api_key import ApiKeyStore


class InMemoryApiKeyStore:
    """In-memory хранилище API-ключей."""

    def __init__(self) -> None:
        self._keys: dict[UUID, ApiKey] = {}
        self._hash_index: dict[str, UUID] = {}  # key_hash → key_id

    async def create_key(
        self,
        tenant_id: UUID,
        name: str,
        scopes: frozenset[str],
        created_by: UUID | None = None,
    ) -> ApiKeyCreateResult:
        raw_key, key_hash = generate_api_key()
        api_key = ApiKey.create(
            tenant_id=tenant_id,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
            created_by=created_by,
        )
        self._keys[api_key.id] = api_key
        self._hash_index[key_hash] = api_key.id
        return ApiKeyCreateResult(raw_key=raw_key, api_key=api_key)

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        key_id = self._hash_index.get(key_hash)
        if key_id is None:
            return None
        return self._keys.get(key_id)

    async def get_by_id(self, key_id: UUID) -> ApiKey | None:
        return self._keys.get(key_id)

    async def list_keys(self, tenant_id: UUID) -> list[ApiKeyInfo]:
        result = []
        for key in self._keys.values():
            if key.tenant_id != tenant_id:
                continue
            result.append(self._to_info(key))
        return result

    async def revoke_key(self, key_id: UUID) -> bool:
        key = self._keys.get(key_id)
        if key is None:
            return False
        # frozen dataclass → создаём новый с revoked_at
        revoked = ApiKey(
            id=key.id,
            tenant_id=key.tenant_id,
            key_hash=key.key_hash,
            name=key.name,
            scopes=key.scopes,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=datetime.now(timezone.utc),
            created_by=key.created_by,
            last_used_at=key.last_used_at,
        )
        self._keys[key_id] = revoked
        return True

    async def update_last_used(self, key_id: UUID) -> None:
        key = self._keys.get(key_id)
        if key is None:
            return
        updated = ApiKey(
            id=key.id,
            tenant_id=key.tenant_id,
            key_hash=key.key_hash,
            name=key.name,
            scopes=key.scopes,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
            created_by=key.created_by,
            last_used_at=datetime.now(timezone.utc),
        )
        self._keys[key_id] = updated

    def clear_all(self) -> None:
        """Очистить всё (для тестов)."""
        self._keys.clear()
        self._hash_index.clear()

    @staticmethod
    def _to_info(key: ApiKey) -> ApiKeyInfo:
        return ApiKeyInfo(
            id=key.id,
            name=key.name,
            scopes=sorted(key.scopes),
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
            last_used_at=key.last_used_at,
            is_active=key.is_active,
        )
