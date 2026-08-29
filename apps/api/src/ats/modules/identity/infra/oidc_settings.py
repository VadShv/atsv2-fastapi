"""Настройки OIDC/SSO (SECURE FIRST, ТЗ §15).

ТЗ §15: OIDC/SSO — конфигурация внешнего identity-провайдера.

Env-переменные (префикс ATS_OIDC_):
    ATS_OIDC_ENABLED=false         — включён ли OIDC/SSO
    ATS_OIDC_PROVIDER=stub         — провайдер: stub/keycloak/cloud.ru/google/custom
    ATS_OIDC_CLIENT_ID=            — client_id в IdP
    ATS_OIDC_CLIENT_SECRET=        — client_secret (SECURE: из env, не в коде)
    ATS_OIDC_ISSUER_URL=           — URL issuer (напр. https://keycloak.local/realms/ats)
    ATS_OIDC_AUTHORIZE_URL=        — authorization endpoint
    ATS_OIDC_TOKEN_URL=            — token endpoint
    ATS_OIDC_USERINFO_URL=         — userinfo endpoint
    ATS_OIDC_REDIRECT_URI=         — callback URI (напр. https://ats.local/api/v1/auth/oidc/callback)
    ATS_OIDC_SCOPE=openid profile email — запрашиваемые scopes
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OIDCSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATS_OIDC_", env_file=".env", extra="ignore"
    )

    enabled: bool = Field(
        default=False,
        description="Включён ли OIDC/SSO",
    )
    provider: str = Field(
        default="stub",
        description="Провайдер: stub/keycloak/cloud.ru/google/custom",
    )
    client_id: str = Field(
        default="",
        description="Client ID в IdP",
    )
    client_secret: str = Field(
        default="",
        description="Client secret (из env, не в коде)",
    )
    issuer_url: str = Field(
        default="",
        description="URL issuer (напр. https://keycloak.local/realms/ats)",
    )
    authorize_url: str = Field(
        default="",
        description="Authorization endpoint URL",
    )
    token_url: str = Field(
        default="",
        description="Token endpoint URL",
    )
    userinfo_url: str = Field(
        default="",
        description="UserInfo endpoint URL",
    )
    redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/oidc/callback",
        description="Callback URI",
    )
    scope: str = Field(
        default="openid profile email",
        description="Запрашиваемые scopes",
    )


settings = OIDCSettings()
