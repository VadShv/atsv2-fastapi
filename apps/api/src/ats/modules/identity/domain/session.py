"""Сессия пользователя (SECURE FIRST).

ТЗ §15: сессии HttpOnly+Secure+SameSite, CSRF-токены, 2FA (TOTP) для админов.
Здесь — доменная модель сессии; transport (cookie/header) — в middleware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

DEFAULT_SESSION_TTL = timedelta(hours=8)


@dataclass(frozen=True)
class Session:
    """Доменная сессия аутентифицированного пользователя."""

    token: str
    user_id: UUID
    tenant_id: UUID
    role_name: str
    issued_at: datetime
    expires_at: datetime
    csrf_token: str = ""
    requires_2fa: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @classmethod
    def create(
        cls,
        user_id: UUID,
        tenant_id: UUID,
        role_name: str,
        ttl: timedelta = DEFAULT_SESSION_TTL,
        requires_2fa: bool = False,
        csrf_token: str = "",
        metadata: dict[str, str] | None = None,
    ) -> Session:
        now = datetime.now(UTC)
        return cls(
            token=_generate_token(),
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=role_name,
            issued_at=now,
            expires_at=now + ttl,
            csrf_token=csrf_token or _generate_token(),
            requires_2fa=requires_2fa,
            metadata=metadata or {},
        )


def _generate_token() -> str:
    """Криптостойкий opaque-токен (не JWT — opaque, валидация через store)."""
    import secrets

    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    import secrets

    return secrets.token_urlsafe(16)
