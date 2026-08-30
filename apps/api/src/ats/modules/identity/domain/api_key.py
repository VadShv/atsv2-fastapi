"""Доменная модель API-ключей (SECURE FIRST, ТЗ §15).

ТЗ §15: API-ключи со скоупами — генерация jugo_live_*, хэш-хранение.

SECURE FIRST:
- Ключи генерируются в формате jugo_live_<random> — префикс для идентификации.
- В БД хранится только SHA-256 хэш ключа — сам ключ нельзя восстановить.
- Ключ ограничен набором permissions (скоупы) + tenant_id.
- Ключ может иметь срок действия (expires_at) и быть отозван (revoked).
- Полный ключ возвращается пользователю ТОЛЬКО один раз — при создании.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

# Префикс для ключей (ТЗ §15)
KEY_PREFIX = "jugo_live_"
KEY_RANDOM_LENGTH = 40  # символов случайной части

# Срок действия по умолчанию (1 год)
DEFAULT_KEY_TTL = timedelta(days=365)


def generate_api_key() -> tuple[str, str]:
    """Сгенерировать API-ключ и его хэш.

    Returns:
        Кортеж (raw_key, key_hash):
        - raw_key: полный ключ в формате jugo_live_<random> (показать один раз)
        - key_hash: SHA-256 хэш для хранения в БД
    """
    random_part = secrets.token_urlsafe(KEY_RANDOM_LENGTH)[:KEY_RANDOM_LENGTH]
    raw_key = f"{KEY_PREFIX}{random_part}"
    key_hash = hash_api_key(raw_key)
    return raw_key, key_hash


def hash_api_key(raw_key: str) -> str:
    """Вычислить SHA-256 хэш ключа для хранения.

    SECURE FIRST: хэш необратим — ключ нельзя восстановить из БД.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def is_api_key(token: str) -> bool:
    """Проверить, имеет ли токен формат API-ключа (префикс jugo_live_)."""
    return token.startswith(KEY_PREFIX)


@dataclass(frozen=True)
class ApiKey:
    """Доменная модель API-ключа (хранится в БД).

    SECURE FIRST: key_hash — единственное, что хранится; raw_key
    возвращается пользователю только при создании и больше недоступен.
    """

    id: UUID
    tenant_id: UUID
    key_hash: str
    name: str  # человекочитаемое название (напр. "Slack integration")
    scopes: frozenset[str] = field(default_factory=frozenset)  # permissions
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by: UUID | None = None
    last_used_at: datetime | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    @property
    def is_active(self) -> bool:
        """Ключ активен: не отозван и не истёк."""
        return not self.is_revoked and not self.is_expired

    def has_scope(self, permission: str) -> bool:
        """Проверить, есть ли permission в скоупах ключа (deny-by-default)."""
        return permission in self.scopes

    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        key_hash: str,
        name: str,
        scopes: frozenset[str] | None = None,
        ttl: timedelta | None = DEFAULT_KEY_TTL,
        created_by: UUID | None = None,
    ) -> ApiKey:
        now = datetime.now(UTC)
        expires = now + ttl if ttl is not None else None
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            key_hash=key_hash,
            name=name,
            scopes=scopes or frozenset(),
            created_at=now,
            expires_at=expires,
            created_by=created_by,
        )


@dataclass(frozen=True)
class ApiKeyCreateResult:
    """Результат создания ключа: полный ключ (один раз) + метаданные."""

    raw_key: str
    api_key: ApiKey


@dataclass(frozen=True)
class ApiKeyInfo:
    """Информация о ключе для списка (без raw_key и без hash)."""

    id: UUID
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    is_active: bool
