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
from ats.modules.identity.infra.in_memory_api_key import InMemoryApiKeyStore
from ats.modules.identity.infra.in_memory_2fa import InMemoryTwoFactorStore
from ats.modules.identity.infra.rate_limiter import (
    AccountLockout,
    LoginRateLimiter,
)
from ats.modules.identity.ports.auth import Authenticator, SessionStore
from ats.modules.identity.infra.oidc_settings import OIDCSettings
from ats.modules.identity.infra.stub_identity_provider import StubIdentityProvider
from ats.modules.identity.ports.api_key import ApiKeyStore
from ats.modules.identity.ports.identity_provider import IdentityProvider
from ats.modules.identity.ports.two_factor import TwoFactorStore

# Singleton-ы для stub/dev-режима (в prod — из DI-контейнера)
_authenticator: Authenticator = InMemoryAuthenticator()
_session_store: SessionStore = InMemorySessionStore()
_rate_limiter: LoginRateLimiter = LoginRateLimiter()
_account_lockout: AccountLockout = AccountLockout()
_two_factor_store: TwoFactorStore = InMemoryTwoFactorStore()
_api_key_store: ApiKeyStore = InMemoryApiKeyStore()
_oidc_settings: OIDCSettings = OIDCSettings()
_identity_provider: IdentityProvider = StubIdentityProvider(_oidc_settings)


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


def get_two_factor_store() -> TwoFactorStore:
    """Получить singleton TwoFactorStore (stub: InMemoryTwoFactorStore)."""
    return _two_factor_store


def get_api_key_store() -> ApiKeyStore:
    """Получить singleton ApiKeyStore (stub: InMemoryApiKeyStore)."""
    return _api_key_store


def get_oidc_settings() -> OIDCSettings:
    """Получить singleton OIDCSettings."""
    return _oidc_settings


def get_identity_provider() -> IdentityProvider:
    """Получить singleton IdentityProvider (stub: StubIdentityProvider)."""
    return _identity_provider


def reset_runtime() -> None:
    """Сбросить всё state (для тестов).

    Очищает сессии, rate-limiter и account-lockout.
    Внимание: только для тестов!
    """
    global _authenticator, _session_store, _rate_limiter, _account_lockout
    global _two_factor_store
    global _api_key_store
    global _oidc_settings, _identity_provider
    _authenticator = InMemoryAuthenticator()
    _session_store = InMemorySessionStore()
    _rate_limiter = LoginRateLimiter()
    _account_lockout = AccountLockout()
    _two_factor_store = InMemoryTwoFactorStore()
    _api_key_store = InMemoryApiKeyStore()
    _oidc_settings = OIDCSettings()
    _identity_provider = StubIdentityProvider(_oidc_settings)
