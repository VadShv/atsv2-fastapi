"""Тесты сессий: rate limit, account lockout, refresh, CSRF (JUGO-021).

SECURE FIRST: проверяем защиту от brute-force и CSRF.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ats.main import app
from ats.modules.identity.infra.csrf import CSRF_COOKIE_NAME
from ats.modules.identity.infra.rate_limiter import (
    AccountLockout,
    LoginRateLimiter,
)
from ats.modules.identity.infra.runtime import (
    get_account_lockout,
    get_rate_limiter,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# LoginRateLimiter — unit-тесты
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_within_limit():
    rl = LoginRateLimiter(max_attempts=5, window_seconds=300)
    for _ in range(4):
        rl.record_attempt("1.2.3.4")
    assert not rl.is_rate_limited("1.2.3.4")
    assert rl.remaining_attempts("1.2.3.4") == 1


def test_rate_limiter_blocks_at_limit():
    rl = LoginRateLimiter(max_attempts=5, window_seconds=300)
    for _ in range(5):
        rl.record_attempt("1.2.3.4")
    assert rl.is_rate_limited("1.2.3.4")
    assert rl.remaining_attempts("1.2.3.4") == 0


def test_rate_limiter_independent_per_ip():
    rl = LoginRateLimiter(max_attempts=5, window_seconds=300)
    for _ in range(5):
        rl.record_attempt("1.1.1.1")
    assert rl.is_rate_limited("1.1.1.1")
    assert not rl.is_rate_limited("2.2.2.2")


def test_rate_limiter_reset_after_success():
    rl = LoginRateLimiter(max_attempts=5, window_seconds=300)
    for _ in range(3):
        rl.record_attempt("1.2.3.4")
    rl.reset("1.2.3.4")
    assert rl.remaining_attempts("1.2.3.4") == 5
    assert not rl.is_rate_limited("1.2.3.4")


# ---------------------------------------------------------------------------
# AccountLockout — unit-тесты
# ---------------------------------------------------------------------------


def test_lockout_not_locked_initially():
    lockout = AccountLockout(max_failures=5, lockout_seconds=900)
    assert not lockout.is_locked("user@ats.local")
    assert lockout.remaining_attempts("user@ats.local") == 5


def test_lockout_locks_after_max_failures():
    lockout = AccountLockout(max_failures=5, lockout_seconds=900)
    for _ in range(5):
        lockout.record_failure("user@ats.local")
    assert lockout.is_locked("user@ats.local")
    assert lockout.remaining_attempts("user@ats.local") == 0
    assert lockout.lockout_remaining_seconds("user@ats.local") > 0


def test_lockout_resets_on_success():
    lockout = AccountLockout(max_failures=5, lockout_seconds=900)
    for _ in range(3):
        lockout.record_failure("user@ats.local")
    lockout.record_success("user@ats.local")
    assert not lockout.is_locked("user@ats.local")
    assert lockout.remaining_attempts("user@ats.local") == 5


# ---------------------------------------------------------------------------
# Rate limit via API — stub-режим (CSRF отключён, но rate limit активен)
# ---------------------------------------------------------------------------


def test_api_login_rate_limit_triggers_429():
    """6-я попытка входа с неверным паролем → 429."""
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit@ats.local", "password": "wrong"},
        )
        assert resp.status_code == 401

    # 6-я попытка — rate limited
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit@ats.local", "password": "wrong"},
    )
    assert resp.status_code == 429


def test_api_login_rate_limit_resets_after_success():
    """Успешный вход сбрасывает rate limit."""
    for i in range(3):
        client.post(
            "/api/v1/auth/login",
            json={"email": "reset@ats.local", "password": "wrong"},
        )
    assert get_rate_limiter().remaining_attempts("testclient") == 2

    # Успешный вход
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@ats.local", "password": "demo"},
    )
    assert resp.status_code == 200
    assert get_rate_limiter().remaining_attempts("testclient") == 5


def test_api_login_account_lockout_after_5_failures():
    """5 неудач → аккаунт блокируется → 429."""
    for i in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "lockme@ats.local", "password": "wrong"},
        )
    assert get_account_lockout().is_locked("lockme@ats.local")

    # Даже с правильным паролем — заблокирован
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "lockme@ats.local", "password": "demo"},
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Refresh — token rotation
# ---------------------------------------------------------------------------


def test_api_refresh_success():
    """Успешный refresh: новый токен, старый недействителен."""
    # Логин
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "refresh@ats.local", "password": "demo"},
    )
    assert resp.status_code == 200
    old_token = resp.json()["token"]

    # Refresh
    resp = client.post(
        "/api/v1/auth/refresh",
        cookies={"ats_session": old_token},
    )
    assert resp.status_code == 200
    new_token = resp.json()["token"]
    assert new_token != old_token

    # Старый токен отозван — проверяем через API /me (stub-режим вернёт demo,
    # но новый refresh старым токеном должен дать 401)
    resp = client.post(
        "/api/v1/auth/refresh",
        cookies={"ats_session": old_token},
    )
    assert resp.status_code == 401
    # Новый токен валиден
    resp = client.post(
        "/api/v1/auth/refresh",
        cookies={"ats_session": new_token},
    )
    assert resp.status_code == 200


def test_api_refresh_old_token_invalid():
    """Старый токен недействителен после refresh."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "rotate@ats.local", "password": "demo"},
    )
    old_token = resp.json()["token"]

    client.post("/api/v1/auth/refresh", cookies={"ats_session": old_token})

    # Повторный refresh старым токеном → 401
    resp = client.post(
        "/api/v1/auth/refresh",
        cookies={"ats_session": old_token},
    )
    assert resp.status_code == 401


def test_api_refresh_no_token_401():
    """Refresh без токена → 401."""
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_api_refresh_invalid_token_401():
    """Refresh с несуществующим токеном → 401."""
    resp = client.post(
        "/api/v1/auth/refresh",
        cookies={"ats_session": "nonexistent-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# CSRF — требует отключения stub-режима
# ---------------------------------------------------------------------------


def test_csrf_unsafe_method_blocked_without_token(monkeypatch):
    """POST без CSRF-токена → 403 (в prod-режиме)."""
    monkeypatch.setenv("ATS_STUB_MODE", "0")
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]


def test_csrf_safe_method_allowed_without_token(monkeypatch):
    """GET без CSRF-токена → OK (безопасные методы не проверяются)."""
    monkeypatch.setenv("ATS_STUB_MODE", "0")
    # /health — безопасный метод, без CSRF
    resp = client.get("/health")
    assert resp.status_code == 200


def test_csrf_exempt_paths_allowed(monkeypatch):
    """Логин и refresh exempt от CSRF (они устанавливают CSRF-токен)."""
    monkeypatch.setenv("ATS_STUB_MODE", "0")
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "csrf@ats.local", "password": "demo"},
    )
    assert resp.status_code in (200, 401, 429)


# ---------------------------------------------------------------------------
# Login cookies — ats_session + ats_csrf
# ---------------------------------------------------------------------------


def test_login_sets_session_and_csrf_cookies():
    """Успешный вход устанавливает both cookies."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "cookies@ats.local", "password": "demo"},
    )
    assert resp.status_code == 200

    cookies = resp.cookies
    assert "ats_session" in cookies
    assert CSRF_COOKIE_NAME in cookies


def test_logout_clears_cookies():
    """Logout удаляет cookies."""
    # Логин
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "logout@ats.local", "password": "demo"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]

    # Logout
    resp = client.post(
        "/api/v1/auth/logout",
        cookies={"ats_session": token},
    )
    assert resp.status_code == 204

    # Сессия отозвана — refresh этим токеном → 401
    resp = client.post(
        "/api/v1/auth/refresh",
        cookies={"ats_session": token},
    )
    assert resp.status_code == 401
