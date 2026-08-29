"""Доменная модель 2FA (SECURE FIRST, ТЗ §15).

ТЗ §15: обязательный 2FA (TOTP) для ролей с админ-правами
(admin, head_of_recruiting).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

# Роли, для которых 2FA обязателен
ROLES_REQUIRING_2FA: frozenset[str] = frozenset({
    "admin",
    "head_of_recruiting",
})


def role_requires_2fa(role_name: str) -> bool:
    """Проверить, обязательна ли 2FA для роли."""
    return role_name in ROLES_REQUIRING_2FA


@dataclass(frozen=True)
class TwoFactorConfig:
    """Конфигурация 2FA для пользователя.

    SECURE FIRST:
    - secret хранится только в БД (не в логах, не в cookie).
    - backup_codes хранятся как SHA-256 хеши.
    - enabled=True только после успешной верификации (setup → verify).
    """

    user_id: UUID
    tenant_id: UUID
    secret: str  # base32
    enabled: bool = False
    backup_code_hashes: list[str] = field(default_factory=list)
    backup_codes_used: list[str] = field(default_factory=list)
    enabled_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def has_unused_backup_codes(self) -> bool:
        """Есть ли неиспользованные backup-коды."""
        return len(self.backup_codes_used) < len(self.backup_code_hashes)

    def remaining_backup_codes(self) -> int:
        """Сколько backup-кодов осталось."""
        return len(self.backup_code_hashes) - len(self.backup_codes_used)


@dataclass(frozen=True)
class TwoFactorSetupResult:
    """Результат setup: секрет + otpauth URI + backup-коды.

    Backup-коды возвращаются в открытом виде ТОЛЬКО один раз — при setup.
    После этого они хранятся только как хеши.
    """

    secret: str
    otpauth_uri: str
    backup_codes: list[str]


@dataclass(frozen=True)
class TwoFactorChallenge:
    """Challenge для входа: пользователь ввёл credentials, но нужен 2FA-код."""

    challenge_token: str
    user_id: UUID
    tenant_id: UUID
    role_name: str
    requires_2fa: bool = True
    expires_at: datetime = field(default_factory=lambda: datetime.now(
        timezone.utc
    ).replace(microsecond=0) + __import__("datetime").timedelta(minutes=5))


def is_2fa_required_for_user(
    role_name: str, config: TwoFactorConfig | None
) -> bool:
    """Определить, требуется ли 2FA для пользователя.

    SECURE FIRST: 2FA требуется, если:
    - Роль в ROLES_REQUIRING_2FA, ИЛИ
    - Пользователь добровольно включил 2FA (config.enabled)
    """
    if config is not None and config.enabled:
        return True
    return role_requires_2fa(role_name)
