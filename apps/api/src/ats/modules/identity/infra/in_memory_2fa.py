"""In-memory реализация TwoFactorStore для stub/dev-режима (SECURE FIRST).

Хранит 2FA-конфиги и challenge-токены в памяти. Для prod — Postgres.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ats.modules.identity.domain.totp import (
    build_otpauth_uri,
    generate_backup_codes,
    generate_secret,
    hash_backup_code,
    verify_totp,
)
from ats.modules.identity.domain.two_factor import (
    TwoFactorChallenge,
    TwoFactorConfig,
    TwoFactorSetupResult,
)

_CHALLENGE_TTL = timedelta(minutes=5)


class InMemoryTwoFactorStore:
    """In-memory хранилище 2FA-конфигов и challenge-токенов."""

    def __init__(self) -> None:
        self._configs: dict[UUID, TwoFactorConfig] = {}
        self._challenges: dict[str, TwoFactorChallenge] = {}

    async def setup(
        self,
        user_id: UUID,
        tenant_id: UUID,
        issuer: str = "ATS Jugo",
        account: str = "",
    ) -> TwoFactorSetupResult:
        secret = generate_secret()
        backup_codes = generate_backup_codes(count=10)
        backup_hashes = [hash_backup_code(c) for c in backup_codes]

        config = TwoFactorConfig(
            user_id=user_id,
            tenant_id=tenant_id,
            secret=secret,
            enabled=False,
            backup_code_hashes=backup_hashes,
        )
        self._configs[user_id] = config

        uri = build_otpauth_uri(
            issuer=issuer,
            account=account or str(user_id),
            secret=secret,
        )
        return TwoFactorSetupResult(
            secret=secret,
            otpauth_uri=uri,
            backup_codes=backup_codes,
        )

    async def verify_and_enable(
        self, user_id: UUID, code: str
    ) -> bool:
        config = self._configs.get(user_id)
        if config is None:
            return False
        if not verify_totp(config.secret, code):
            return False
        # Включаем 2FA
        enabled_config = TwoFactorConfig(
            user_id=config.user_id,
            tenant_id=config.tenant_id,
            secret=config.secret,
            enabled=True,
            backup_code_hashes=config.backup_code_hashes,
            backup_codes_used=config.backup_codes_used,
            enabled_at=datetime.now(timezone.utc),
            created_at=config.created_at,
        )
        self._configs[user_id] = enabled_config
        return True

    async def get_config(self, user_id: UUID) -> TwoFactorConfig | None:
        return self._configs.get(user_id)

    async def verify_code(
        self, user_id: UUID, code: str
    ) -> bool:
        config = self._configs.get(user_id)
        if config is None or not config.enabled:
            return False
        return verify_totp(config.secret, code)

    async def verify_backup_code(
        self, user_id: UUID, code: str
    ) -> bool:
        config = self._configs.get(user_id)
        if config is None or not config.enabled:
            return False
        code_hash = hash_backup_code(code.strip())
        if code_hash in config.backup_codes_used:
            return False
        if code_hash not in config.backup_code_hashes:
            return False
        # Помечаем как использованный
        used = list(config.backup_codes_used) + [code_hash]
        updated = TwoFactorConfig(
            user_id=config.user_id,
            tenant_id=config.tenant_id,
            secret=config.secret,
            enabled=config.enabled,
            backup_code_hashes=config.backup_code_hashes,
            backup_codes_used=used,
            enabled_at=config.enabled_at,
            created_at=config.created_at,
        )
        self._configs[user_id] = updated
        return True

    async def disable(self, user_id: UUID) -> None:
        self._configs.pop(user_id, None)

    async def create_challenge(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role_name: str,
    ) -> TwoFactorChallenge:
        token = secrets.token_urlsafe(32)
        challenge = TwoFactorChallenge(
            challenge_token=token,
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=role_name,
            requires_2fa=True,
            expires_at=datetime.now(timezone.utc) + _CHALLENGE_TTL,
        )
        self._challenges[token] = challenge
        return challenge

    async def get_challenge(
        self, challenge_token: str
    ) -> TwoFactorChallenge | None:
        challenge = self._challenges.get(challenge_token)
        if challenge is None:
            return None
        if datetime.now(timezone.utc) >= challenge.expires_at:
            self._challenges.pop(challenge_token, None)
            return None
        return challenge

    async def revoke_challenge(
        self, challenge_token: str
    ) -> None:
        self._challenges.pop(challenge_token, None)

    def clear_all(self) -> None:
        """Очистить всё (для тестов)."""
        self._configs.clear()
        self._challenges.clear()
