"""Порт IdentityProvider — абстракция OIDC/SSO (SECURE FIRST, ТЗ §15).

ТЗ §15: OIDC/SSO — абстракция identity-провайдера.
Любой внешний IdP (Keycloak, Cloud.ru IAM, Google, и др.) реализует этот интерфейс.

WHITEBOX AI: протокол полностью прозрачен.
Домен зависит от интерфейса; реализации (HTTP-клиент / stub) — в infra.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.identity.domain.oidc import (
    OIDCAuthRequest,
    OIDCCallbackResult,
    OIDCUserInfo,
)


@runtime_checkable
class IdentityProvider(Protocol):
    """Порт: identity-провайдер (OIDC/SSO).

    Flow:
    1. authorize() → возвращает URL для редиректа пользователя к IdP.
    2. Пользователь логинится в IdP, IdP редиректит обратно на callback.
    3. exchange_code() → обменивает code на токены + получает userinfo.
    """

    @property
    def provider_name(self) -> str:
        """Название провайдера (напр. 'keycloak', 'cloud.ru')."""
        ...

    async def authorize(self, redirect_uri: str) -> OIDCAuthRequest:
        """Сгенерировать authorization request (URL + state + PKCE).

        SECURE FIRST: state для CSRF-защиты, PKCE для защиты code interception.
        """
        ...

    async def exchange_code(
        self,
        code: str,
        state: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OIDCCallbackResult:
        """Обменять authorization code на токены + получить userinfo.

        SECURE FIRST: проверка state (CSRF), code_verifier (PKCE).
        Возвращает токены + userinfo для создания локальной сессии.
        """
        ...

    async def get_userinfo(self, access_token: str) -> OIDCUserInfo:
        """Получить userinfo по access_token (для refresh/profiling)."""
        ...

    async def verify_state(self, state: str) -> bool:
        """Проверить state (защита от CSRF в OIDC callback).

        SECURE FIRST: state должен совпадать с тем, что выдан в authorize().
        """
        ...
