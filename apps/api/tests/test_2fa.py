"""Тесты 2FA (TOTP): setup, verify, backup codes, required roles (JUGO-023).

SECURE FIRST: проверяем обязательное 2FA для админ-ролей и protection flow.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ats.main import app
from ats.modules.identity.domain.totp import (
    build_otpauth_uri,
    generate_backup_codes,
    generate_secret,
    hash_backup_code,
    totp_code,
    verify_totp,
)
from ats.modules.identity.domain.two_factor import (
    ROLES_REQUIRING_2FA,
    TwoFactorConfig,
    is_2fa_required_for_user,
    role_requires_2fa,
)
from ats.modules.identity.infra.in_memory_2fa import InMemoryTwoFactorStore
from ats.modules.identity.infra.runtime import (
    get_two_factor_store,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# TOTP — unit-тесты (domain/totp.py)
# ---------------------------------------------------------------------------


def test_generate_secret_length():
    secret = generate_secret()
    # base32 без padding, 20 байт = 32 chars
    assert len(secret) >= 30
    assert "=" not in secret


def test_generate_secret_unique():
    s1 = generate_secret()
    s2 = generate_secret()
    assert s1 != s2


def test_totp_code_format():
    secret = generate_secret()
    code = totp_code(secret)
    assert len(code) == 6
    assert code.isdigit()


def test_verify_totp_current_code():
    secret = generate_secret()
    code = totp_code(secret)
    assert verify_totp(secret, code)


def test_verify_totp_wrong_code():
    secret = generate_secret()
    assert not verify_totp(secret, "000000")


def test_verify_totp_tolerance():
    """Код из предыдущего окна принимается (tolerance=1)."""
    import time

    secret = generate_secret()
    # Код из 30 секунд назад
    old_timestamp = int(time.time()) - 30
    old_code = totp_code(secret, timestamp=old_timestamp)
    assert verify_totp(secret, old_code, tolerance_windows=1)


def test_verify_totp_no_tolerance_rejects_old():
    """Код из предыдущего окна отклоняется при tolerance=0."""
    import time

    secret = generate_secret()
    old_timestamp = int(time.time()) - 30
    old_code = totp_code(secret, timestamp=old_timestamp)
    assert not verify_totp(secret, old_code, tolerance_windows=0)


def test_verify_totp_empty_inputs():
    assert not verify_totp("", "123456")
    assert not verify_totp(generate_secret(), "")


def test_build_otpauth_uri():
    secret = generate_secret()
    uri = build_otpauth_uri("ATS Jugo", "admin@ats.local", secret)
    assert uri.startswith("otpauth://totp/")
    assert "secret=" + secret in uri
    assert "issuer=ATS+Jugo" in uri
    assert "digits=6" in uri
    assert "period=30" in uri


# ---------------------------------------------------------------------------
# Backup codes — unit-тесты
# ---------------------------------------------------------------------------


def test_generate_backup_codes_count():
    codes = generate_backup_codes(count=10)
    assert len(codes) == 10


def test_generate_backup_codes_format():
    codes = generate_backup_codes(count=5)
    for code in codes:
        # Формат: XXXX-XXXX-XXXX-XXXX
        parts = code.split("-")
        assert len(parts) == 4
        for part in parts:
            assert len(part) == 4


def test_generate_backup_codes_unique():
    codes = generate_backup_codes(count=10)
    assert len(set(codes)) == 10


def test_hash_backup_code_deterministic():
    code = "abcd-1234-ef56-7890"
    h1 = hash_backup_code(code)
    h2 = hash_backup_code(code)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_backup_code_not_reversible():
    code = "abcd-1234-ef56-7890"
    h = hash_backup_code(code)
    assert code not in h


# ---------------------------------------------------------------------------
# Two-factor domain — unit-тесты
# ---------------------------------------------------------------------------


def test_roles_requiring_2fa():
    assert "admin" in ROLES_REQUIRING_2FA
    assert "head_of_recruiting" in ROLES_REQUIRING_2FA
    assert "recruiter" not in ROLES_REQUIRING_2FA


def test_role_requires_2fa():
    assert role_requires_2fa("admin")
    assert role_requires_2fa("head_of_recruiting")
    assert not role_requires_2fa("recruiter")
    assert not role_requires_2fa("viewer")


def test_is_2fa_required_for_admin_without_config():
    assert is_2fa_required_for_user("admin", None) is True


def test_is_2fa_required_for_recruiter_without_config():
    assert is_2fa_required_for_user("recruiter", None) is False


def test_is_2fa_required_when_enabled():
    """Если 2FA включена добровольно — требуется для любой роли."""
    from uuid import UUID

    config = TwoFactorConfig(
        user_id=UUID(int=1),
        tenant_id=UUID(int=1),
        secret="JBSWY3DPEHPK3PXP",
        enabled=True,
    )
    assert is_2fa_required_for_user("recruiter", config) is True


def test_two_factor_config_remaining_backup_codes():
    from uuid import UUID

    config = TwoFactorConfig(
        user_id=UUID(int=1),
        tenant_id=UUID(int=1),
        secret="JBSWY3DPEHPK3PXP",
        enabled=True,
        backup_code_hashes=["h1", "h2", "h3"],
        backup_codes_used=["h1"],
    )
    assert config.remaining_backup_codes() == 2
    assert config.has_unused_backup_codes is True


def test_two_factor_config_all_backup_codes_used():
    from uuid import UUID

    config = TwoFactorConfig(
        user_id=UUID(int=1),
        tenant_id=UUID(int=1),
        secret="JBSWY3DPEHPK3PXP",
        enabled=True,
        backup_code_hashes=["h1", "h2"],
        backup_codes_used=["h1", "h2"],
    )
    assert config.remaining_backup_codes() == 0
    assert config.has_unused_backup_codes is False


# ---------------------------------------------------------------------------
# InMemoryTwoFactorStore — unit-тесты
# ---------------------------------------------------------------------------

TENANT_ID = "00000000-0000-0000-0000-000000000001"
ADMIN_USER_ID = "00000000-0000-0000-0000-000000000010"


@pytest.mark.asyncio
async def test_store_setup_creates_disabled_config():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
        account="admin@ats.local",
    )
    assert result.secret
    assert result.otpauth_uri.startswith("otpauth://")
    assert len(result.backup_codes) == 10

    config = await store.get_config(UUID(ADMIN_USER_ID))
    assert config is not None
    assert config.enabled is False  # disabled until verify
    assert len(config.backup_code_hashes) == 10


@pytest.mark.asyncio
async def test_store_verify_and_enable():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    code = totp_code(result.secret)
    success = await store.verify_and_enable(UUID(ADMIN_USER_ID), code)
    assert success is True

    config = await store.get_config(UUID(ADMIN_USER_ID))
    assert config.enabled is True
    assert config.enabled_at is not None


@pytest.mark.asyncio
async def test_store_verify_and_enable_wrong_code():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    success = await store.verify_and_enable(UUID(ADMIN_USER_ID), "000000")
    assert success is False

    config = await store.get_config(UUID(ADMIN_USER_ID))
    assert config.enabled is False


@pytest.mark.asyncio
async def test_store_verify_code_after_enable():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    await store.verify_and_enable(UUID(ADMIN_USER_ID), totp_code(result.secret))

    # Новый код (текущий)
    code = totp_code(result.secret)
    assert await store.verify_code(UUID(ADMIN_USER_ID), code) is True


@pytest.mark.asyncio
async def test_store_verify_code_wrong():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    await store.verify_and_enable(UUID(ADMIN_USER_ID), totp_code(result.secret))

    assert await store.verify_code(UUID(ADMIN_USER_ID), "000000") is False


@pytest.mark.asyncio
async def test_store_backup_code_valid():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    await store.verify_and_enable(UUID(ADMIN_USER_ID), totp_code(result.secret))

    backup = result.backup_codes[0]
    assert await store.verify_backup_code(UUID(ADMIN_USER_ID), backup) is True


@pytest.mark.asyncio
async def test_store_backup_code_single_use():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    await store.verify_and_enable(UUID(ADMIN_USER_ID), totp_code(result.secret))

    backup = result.backup_codes[0]
    # Первое использование — OK
    assert await store.verify_backup_code(UUID(ADMIN_USER_ID), backup) is True
    # Повторное — отклонено
    assert await store.verify_backup_code(UUID(ADMIN_USER_ID), backup) is False


@pytest.mark.asyncio
async def test_store_backup_code_invalid():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    result = await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    await store.verify_and_enable(UUID(ADMIN_USER_ID), totp_code(result.secret))

    assert await store.verify_backup_code(
        UUID(ADMIN_USER_ID), "invalid-code"
    ) is False


@pytest.mark.asyncio
async def test_store_disable():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    await store.setup(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
    )
    await store.verify_and_enable(UUID(ADMIN_USER_ID), "dummy")
    await store.disable(UUID(ADMIN_USER_ID))
    assert await store.get_config(UUID(ADMIN_USER_ID)) is None


@pytest.mark.asyncio
async def test_store_challenge_lifecycle():
    store = InMemoryTwoFactorStore()
    from uuid import UUID

    challenge = await store.create_challenge(
        user_id=UUID(ADMIN_USER_ID),
        tenant_id=UUID(TENANT_ID),
        role_name="admin",
    )
    assert challenge.challenge_token

    fetched = await store.get_challenge(challenge.challenge_token)
    assert fetched is not None
    assert fetched.user_id == UUID(ADMIN_USER_ID)

    await store.revoke_challenge(challenge.challenge_token)
    assert await store.get_challenge(challenge.challenge_token) is None


# ---------------------------------------------------------------------------
# 2FA API — integration через TestClient
# ---------------------------------------------------------------------------


def test_api_2fa_setup_in_stub_mode():
    """Setup в stub-режиме — создаётся конфиг, возвращается secret + URI."""
    resp = client.post("/api/v1/auth/2fa/setup")
    assert resp.status_code == 200
    data = resp.json()
    assert "secret" in data
    assert "otpauth_uri" in data
    assert data["otpauth_uri"].startswith("otpauth://")
    assert len(data["backup_codes"]) == 10


def test_api_2fa_enable_with_valid_code():
    """Enable с корректным TOTP-кодом → enabled=True."""
    # Setup
    resp = client.post("/api/v1/auth/2fa/setup")
    assert resp.status_code == 200
    secret = resp.json()["secret"]

    # Enable с текущим кодом
    code = totp_code(secret)
    resp = client.post("/api/v1/auth/2fa/enable", json={"code": code})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_api_2fa_enable_with_wrong_code():
    """Enable с неверным кодом → 400."""
    client.post("/api/v1/auth/2fa/setup")
    resp = client.post("/api/v1/auth/2fa/enable", json={"code": "000000"})
    assert resp.status_code == 400


def test_api_2fa_status():
    """Status возвращает enabled/required/remaining_backup_codes."""
    # Setup + enable
    resp = client.post("/api/v1/auth/2fa/setup")
    secret = resp.json()["secret"]
    client.post("/api/v1/auth/2fa/enable", json={"code": totp_code(secret)})

    resp = client.get("/api/v1/auth/2fa/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["remaining_backup_codes"] == 10


def test_api_2fa_disable_with_valid_code():
    """Disable с корректным кодом → enabled=False."""
    resp = client.post("/api/v1/auth/2fa/setup")
    secret = resp.json()["secret"]
    client.post("/api/v1/auth/2fa/enable", json={"code": totp_code(secret)})

    resp = client.post(
        "/api/v1/auth/2fa/disable", json={"code": totp_code(secret)}
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_api_2fa_disable_with_wrong_code():
    """Disable с неверным кодом → 400."""
    resp = client.post("/api/v1/auth/2fa/setup")
    secret = resp.json()["secret"]
    client.post("/api/v1/auth/2fa/enable", json={"code": totp_code(secret)})

    resp = client.post(
        "/api/v1/auth/2fa/disable", json={"code": "000000"}
    )
    assert resp.status_code == 400
