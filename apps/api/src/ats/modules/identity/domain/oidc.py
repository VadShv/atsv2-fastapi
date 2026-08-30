"""Доменные модели OIDC/SSO (SECURE FIRST, ТЗ §15).

ТЗ §15: OIDC/SSO — абстракция identity-провайдера.
Реализация подключения внешнего OIDC (Keycloak, Cloud.ru IAM, и др.) — v1.1.
Здесь — интерфейс и модели данных.

WHITEBOX AI: протокол полностью прозрачен, любая реализация
OIDC-провайдера соответствует одному интерфейсу.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class OIDCProvider(StrEnum):
    """Поддерживаемые identity-провайдеры."""

    STUB = "stub"  # для dev/тестов
    KEYCLOAK = "keycloak"
    CLOUD_RU = "cloud.ru"
    GOOGLE = "google"
    CUSTOM = "custom"


@dataclass(frozen=True)
class OIDCAuthRequest:
    """Запрос на авторизацию (redirect к IdP).

    Содержит URL для редиректа пользователя к identity-провайдеру,
    state (для защиты от CSRF) и PKCE code_verifier.
    """

    authorization_url: str
    state: str  # CSRF protection
    code_verifier: str  # PKCE
    code_challenge: str  # PKCE S256


@dataclass(frozen=True)
class OIDCTokenResponse:
    """Ответ от token endpoint после обмена code на токены."""

    access_token: str
    id_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str = ""
    scope: str = ""


@dataclass(frozen=True)
class OIDCUserInfo:
    """UserInfo из IdP — данные аутентифицированного пользователя.

    SECURE FIRST: email верифицируется (email_verified) перед привязкой
    к локальному аккаунту.
    """

    subject: str  # уникальный ID в IdP (sub claim)
    email: str
    email_verified: bool = False
    full_name: str = ""
    given_name: str = ""
    family_name: str = ""
    tenant_id: UUID | None = None  # если IdP мульти-тенантный
    roles: list[str] = field(default_factory=list)
    raw_claims: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OIDCCallbackResult:
    """Результат callback: токены + userinfo → для создания локальной сессии."""

    tokens: OIDCTokenResponse
    user_info: OIDCUserInfo
    is_new_user: bool = False  # True если первый вход (нужно создать аккаунт)


def generate_state() -> str:
    """Сгенерировать state для CSRF-защиты OIDC-флоу."""
    import secrets

    return secrets.token_urlsafe(32)


def generate_pkce_verifier() -> str:
    """Сгенерировать PKCE code_verifier (RFC 7636)."""
    import secrets

    return secrets.token_urlsafe(64)


def generate_pkce_challenge(verifier: str) -> str:
    """Вычислить PKCE code_challenge (S256) из code_verifier.

    S256 method: BASE64URL(SHA256(code_verifier))
    """
    import base64
    import hashlib

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
