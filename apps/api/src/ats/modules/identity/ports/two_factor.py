"""Порт TwoFactorStore (SECURE FIRST, ТЗ §15).

Хранение конфигураций 2FA и challenge-токенов.
Домен зависит от интерфейса; реализация (Postgres / in-memory) — в infra.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from uuid import UUID

from ats.modules.identity.domain.two_factor import (
    TwoFactorChallenge,
    TwoFactorConfig,
    TwoFactorSetupResult,
)


@runtime_checkable
class TwoFactorStore(Protocol):
    """Порт: хранение 2FA-конфигураций и challenge-токенов."""

    async def setup(
        self,
        user_id: UUID,
        tenant_id: UUID,
        issuer: str = "ATS Jugo",
        account: str = "",
    ) -> TwoFactorSetupResult:
        """Создать конфигурацию 2FA: сгенерировать secret + backup codes.

        Возвращает секрет, otpauth URI и backup-коды (в открытом виде —
        только один раз). Конфиг остаётся disabled до вызова verify().
        """
        ...

    async def verify_and_enable(
        self, user_id: UUID, code: str
    ) -> bool:
        """Проверить TOTP-код и включить 2FA (enabled=True).

        Returns:
            True если код верный и 2FA включена.
        """
        ...

    async def get_config(self, user_id: UUID) -> TwoFactorConfig | None:
        """Получить конфигурацию 2FA пользователя (или None)."""
        ...

    async def verify_code(
        self, user_id: UUID, code: str
    ) -> bool:
        """Проверить TOTP-код (для входа). Конфиг должен быть enabled.

        Returns:
            True если код верный.
        """
        ...

    async def verify_backup_code(
        self, user_id: UUID, code: str
    ) -> bool:
        """Проверить backup-код (одноразовый).

        SECURE FIRST: код помечается как использованный, повторное
        использование невозможно.
        """
        ...

    async def disable(self, user_id: UUID) -> None:
        """Отключить 2FA (удалить конфиг)."""
        ...

    async def create_challenge(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role_name: str,
    ) -> TwoFactorChallenge:
        """Создать challenge-токен для входа (после credentials, до 2FA).

        Challenge действителен 5 минут.
        """
        ...

    async def get_challenge(
        self, challenge_token: str
    ) -> TwoFactorChallenge | None:
        """Получить challenge по токену. None — не найден или истёк."""
        ...

    async def revoke_challenge(
        self, challenge_token: str
    ) -> None:
        """Отозвать challenge (после успешного 2FA или logout)."""
        ...
