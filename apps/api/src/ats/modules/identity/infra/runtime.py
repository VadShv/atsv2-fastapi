"""Runtime singleton-ы identity-модуля.

В stub/dev-режиме: InMemory-реализации.
В prod-режиме: реальные реализации (Postgres sessions, Redis rate-limiter) —
подключаются через DI-контейнер в Wave 1.

SECURE FIRST: singletons инкапсулируют state-changing infra (rate limiter,
account lockout), чтобы state корректно сохранялся между запросами.
"""

from __future__ import annotations

from ats.modules.identity.infra.in_memory_auth import (
    InMemoryAuthenticator,
    InMemorySessionStore,
)
from ats.modules.identity.infra.rate_limiter import (
    AccountLockout,
    LoginRateLimiter,
)
from ats.modules.identity.ports.auth import Authenticator, SessionStore

# Singleton-ы для stub/dev-режима (в prod — из DI-контейнера)
_authenticator: Authenticator = InMemoryAuthenticator()
_session_store: SessionStore = InMemorySessionStore()
_rate_limiter: LoginRateLimiter = LoginRateLimiter()
_account_lockout: AccountLockout = AccountLockout()


def get_authenticator() -> Authenticator:
    """Получить singleton Authenticator (stub: InMemoryAuthenticator)."""
    return _authenticator


def get_session_store() -> SessionStore:
    """Получить singleton SessionStore (stub: InMemorySessionStore)."""
    return _session_store


def get_rate_limiter() -> LoginRateLimiter:
    """Получить singleton LoginRateLimiter."""
    return _rate_limiter


def get_account_lockout() -> AccountLockout:
    """Получить singleton AccountLockout."""
    return _account_lockout


def reset_runtime() -> None:
    """Сбросить всё state (для тестов).

    Очищает сессии, rate-limiter и account-lockout.
    Внимание: только для тестов!
    """
    global _authenticator, _session_store, _rate_limiter, _account_lockout
    _authenticator = InMemoryAuthenticator()
    _session_store = InMemorySessionStore()
    _rate_limiter = LoginRateLimiter()
    _account_lockout = AccountLockout()
