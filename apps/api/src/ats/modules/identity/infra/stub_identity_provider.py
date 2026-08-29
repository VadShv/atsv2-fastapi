"""Stub-реализация IdentityProvider для dev/тестов (SECURE FIRST, ТЗ §15).

Имитирует OIDC-флоу без реального HTTP-вызова к IdP.
В prod — HTTP-клиент к Keycloak/Cloud.ru IAM (реализация в v1.1).

WHITEBOX AI: алгоритм полностью прозрачен — те же шаги, что и реальный OIDC.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.modules.identity.domain.oidc import (
    OIDCAuthRequest,
    OIDCCallbackResult,
    OIDCTokenResponse,
    OIDCUserInfo,
    generate_pkce_challenge,
    generate_pkce_verifier,
    generate_state,
)
from ats.modules.identity.infra.oidc_settings import OIDCSettings

logger = logging.getLogger(__name__)


class StubIdentityProvider:
    """Stub identity-провайдер: имитирует OIDC flow для dev/тестов.

    SECURE FIRST: state и PKCE генерируются так же, как в реальном OIDC.
    Возвращает предсказуемый userinfo (demo-пользователь).
    """

    def __init__(self, settings: OIDCSettings | None = None) -> None:
        self._settings = settings or OIDCSettings()
        # In-memory хранилище state → code_verifier (для callback)
        self._pending: dict[str, str] = {}  # state → code_verifier

    @property
    def provider_name(self) -> str:
        return "stub"

    async def authorize(self, redirect_uri: str) -> OIDCAuthRequest:
        """Сгенерировать authorization request (URL + state + PKCE)."""
        state = generate_state()
        code_verifier = generate_pkce_verifier()
        code_challenge = generate_pkce_challenge(code_verifier)

        # Сохраняем для callback
        self._pending[state] = code_verifier

        # Stub URL: не редиректит к реальному IdP, а содержит все параметры
        authorize_url = (
            f"{self._settings.authorize_url or 'https://stub-idp.local/authorize'}"
            f"?response_type=code"
            f"&client_id={self._settings.client_id or 'stub-client'}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={self._settings.scope.replace(' ', '+')}"
            f"&state={state}"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
        )

        logger.info("OIDC stub authorize: state=%s", state[:8])

        return OIDCAuthRequest(
            authorization_url=authorize_url,
            state=state,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
        )

    async def exchange_code(
        self,
        code: str,
        state: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OIDCCallbackResult:
        """Обменять code на токены (stub: генерирует фейковые токены)."""
        # SECURE FIRST: проверка state
        if not await self.verify_state(state):
            raise ValueError("Invalid state (CSRF protection)")

        # Проверка PKCE
        stored_verifier = self._pending.get(state, "")
        if code_verifier != stored_verifier:
            raise ValueError("Invalid PKCE code_verifier")

        # Удаляем использованный state
        self._pending.pop(state, None)

        # Stub: генерируем предсказуемые токены
        import secrets

        access_token = f"stub_access_{secrets.token_urlsafe(32)}"
        id_token = f"stub_id_{secrets.token_urlsafe(32)}"

        tokens = OIDCTokenResponse(
            access_token=access_token,
            id_token=id_token,
            token_type="Bearer",
            expires_in=3600,
            scope=self._settings.scope,
        )

        user_info = OIDCUserInfo(
            subject="stub-user-001",
            email="sso-user@ats.local",
            email_verified=True,
            full_name="SSO Demo User",
            roles=["recruiter"],
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        )

        logger.info("OIDC stub exchange_code success: sub=%s", user_info.subject)

        return OIDCCallbackResult(
            tokens=tokens,
            user_info=user_info,
            is_new_user=False,
        )

    async def get_userinfo(self, access_token: str) -> OIDCUserInfo:
        """Получить userinfo по access_token (stub: возвращает demo)."""
        if not access_token.startswith("stub_access_"):
            raise ValueError("Invalid access token")
        return OIDCUserInfo(
            subject="stub-user-001",
            email="sso-user@ats.local",
            email_verified=True,
            full_name="SSO Demo User",
            roles=["recruiter"],
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        )

    async def verify_state(self, state: str) -> bool:
        """Проверить, что state был выдан в authorize()."""
        return state in self._pending

    def clear_pending(self) -> None:
        """Очистить pending state (для тестов)."""
        self._pending.clear()
