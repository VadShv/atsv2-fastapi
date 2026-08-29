"""Тесты OIDC/SSO: протокол, stub-реализация, endpoints (JUGO-026).

SECURE FIRST: проверяем state (CSRF) + PKCE защиту.
WHITEBOX AI: протокол прозрачен, stub имитирует реальный OIDC flow.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ats.main import app
from ats.modules.identity.domain.oidc import (
    OIDCAuthRequest,
    OIDCCallbackResult,
    OIDCProvider,
    OIDCTokenResponse,
    OIDCUserInfo,
    generate_pkce_challenge,
    generate_pkce_verifier,
    generate_state,
)
from ats.modules.identity.infra.oidc_settings import OIDCSettings
from ats.modules.identity.infra.stub_identity_provider import StubIdentityProvider
from ats.modules.identity.infra.runtime import get_identity_provider, get_oidc_settings
from ats.modules.identity.ports.identity_provider import IdentityProvider

from uuid import UUID

client = TestClient(app)


# ---------------------------------------------------------------------------
# OIDC domain — unit-тесты
# ---------------------------------------------------------------------------


def test_oidc_provider_enum():
    assert OIDCProvider.STUB == "stub"
    assert OIDCProvider.KEYCLOAK == "keycloak"
    assert OIDCProvider.CLOUD_RU == "cloud.ru"


def test_generate_state_unique():
    s1 = generate_state()
    s2 = generate_state()
    assert s1 != s2
    assert len(s1) >= 30


def test_generate_pkce_verifier_unique():
    v1 = generate_pkce_verifier()
    v2 = generate_pkce_verifier()
    assert v1 != v2
    assert len(v1) >= 40


def test_pkce_challenge_deterministic():
    verifier = generate_pkce_verifier()
    c1 = generate_pkce_challenge(verifier)
    c2 = generate_pkce_challenge(verifier)
    assert c1 == c2


def test_pkce_challenge_different_verifiers():
    v1 = generate_pkce_verifier()
    v2 = generate_pkce_verifier()
    assert generate_pkce_challenge(v1) != generate_pkce_challenge(v2)


def test_oidc_auth_request_dataclass():
    req = OIDCAuthRequest(
        authorization_url="https://idp/authorize?...",
        state="abc123",
        code_verifier="verifier123",
        code_challenge="challenge123",
    )
    assert req.authorization_url.startswith("https://")
    assert req.state == "abc123"


def test_oidc_token_response_defaults():
    tokens = OIDCTokenResponse(
        access_token="at",
        id_token="it",
    )
    assert tokens.token_type == "Bearer"
    assert tokens.expires_in == 3600


def test_oidc_user_info_defaults():
    info = OIDCUserInfo(subject="sub123", email="user@test.local")
    assert info.email_verified is False
    assert info.roles == []


def test_oidc_callback_result():
    tokens = OIDCTokenResponse(access_token="at", id_token="it")
    info = OIDCUserInfo(subject="sub", email="e@t.local")
    result = OIDCCallbackResult(tokens=tokens, user_info=info, is_new_user=True)
    assert result.is_new_user is True


# ---------------------------------------------------------------------------
# OIDCSettings — unit-тесты
# ---------------------------------------------------------------------------


def test_oidc_settings_defaults():
    settings = OIDCSettings()
    assert settings.enabled is False
    assert settings.provider == "stub"
    assert settings.scope == "openid profile email"
    assert settings.client_id == ""
    assert settings.client_secret == ""


def test_oidc_settings_from_env(monkeypatch):
    monkeypatch.setenv("ATS_OIDC_ENABLED", "true")
    monkeypatch.setenv("ATS_OIDC_PROVIDER", "keycloak")
    monkeypatch.setenv("ATS_OIDC_CLIENT_ID", "my-client")
    monkeypatch.setenv("ATS_OIDC_CLIENT_SECRET", "secret123")
    monkeypatch.setenv("ATS_OIDC_ISSUER_URL", "https://kc.local/realms/ats")

    settings = OIDCSettings()
    assert settings.enabled is True
    assert settings.provider == "keycloak"
    assert settings.client_id == "my-client"
    assert settings.client_secret == "secret123"
    assert settings.issuer_url == "https://kc.local/realms/ats"


# ---------------------------------------------------------------------------
# StubIdentityProvider — unit-тесты
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_provider_is_identity_provider():
    provider = StubIdentityProvider()
    assert isinstance(provider, IdentityProvider)
    assert provider.provider_name == "stub"


@pytest.mark.asyncio
async def test_stub_provider_authorize():
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")

    assert auth_req.authorization_url.startswith("https://")
    assert "response_type=code" in auth_req.authorization_url
    assert "state=" in auth_req.authorization_url
    assert "code_challenge=" in auth_req.authorization_url
    assert "code_challenge_method=S256" in auth_req.authorization_url
    assert auth_req.state
    assert auth_req.code_verifier
    assert auth_req.code_challenge


@pytest.mark.asyncio
async def test_stub_provider_exchange_code_success():
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")

    result = await provider.exchange_code(
        code="stub-code-123",
        state=auth_req.state,
        code_verifier=auth_req.code_verifier,
        redirect_uri="https://ats.local/callback",
    )

    assert result.tokens.access_token.startswith("stub_access_")
    assert result.tokens.id_token.startswith("stub_id_")
    assert result.tokens.token_type == "Bearer"
    assert result.user_info.subject == "stub-user-001"
    assert result.user_info.email == "sso-user@ats.local"
    assert result.user_info.email_verified is True


@pytest.mark.asyncio
async def test_stub_provider_exchange_code_invalid_state():
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")

    with pytest.raises(ValueError, match="Invalid state"):
        await provider.exchange_code(
            code="stub-code",
            state="wrong-state",
            code_verifier=auth_req.code_verifier,
            redirect_uri="https://ats.local/callback",
        )


@pytest.mark.asyncio
async def test_stub_provider_exchange_code_invalid_pkce():
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")

    with pytest.raises(ValueError, match="Invalid PKCE"):
        await provider.exchange_code(
            code="stub-code",
            state=auth_req.state,
            code_verifier="wrong-verifier",
            redirect_uri="https://ats.local/callback",
        )


@pytest.mark.asyncio
async def test_stub_provider_verify_state():
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")

    assert await provider.verify_state(auth_req.state) is True
    assert await provider.verify_state("nonexistent") is False


@pytest.mark.asyncio
async def test_stub_provider_get_userinfo():
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")
    result = await provider.exchange_code(
        code="stub-code",
        state=auth_req.state,
        code_verifier=auth_req.code_verifier,
        redirect_uri="https://ats.local/callback",
    )

    info = await provider.get_userinfo(result.tokens.access_token)
    assert info.subject == "stub-user-001"
    assert info.email == "sso-user@ats.local"


@pytest.mark.asyncio
async def test_stub_provider_get_userinfo_invalid_token():
    provider = StubIdentityProvider()
    with pytest.raises(ValueError, match="Invalid access token"):
        await provider.get_userinfo("invalid-token")


@pytest.mark.asyncio
async def test_stub_provider_state_single_use():
    """State удаляется после exchange_code (нельзя переиспользовать)."""
    provider = StubIdentityProvider()
    auth_req = await provider.authorize("https://ats.local/callback")

    await provider.exchange_code(
        code="stub-code",
        state=auth_req.state,
        code_verifier=auth_req.code_verifier,
        redirect_uri="https://ats.local/callback",
    )

    # Повторное использование → invalid state
    assert await provider.verify_state(auth_req.state) is False


# ---------------------------------------------------------------------------
# OIDC API endpoints — integration через TestClient
# ---------------------------------------------------------------------------


def test_api_oidc_start_disabled():
    """OIDC start когда отключён → 503."""
    resp = client.post("/api/v1/auth/oidc/start")
    assert resp.status_code == 503


def test_api_oidc_start_enabled(monkeypatch):
    """OIDC start когда включён → authorization_url + state + code_verifier."""
    monkeypatch.setenv("ATS_OIDC_ENABLED", "true")
    # Пересоздаём settings с включённым OIDC
    from ats.modules.identity.infra import runtime

    runtime._oidc_settings = OIDCSettings(enabled=True, provider="stub")
    runtime._identity_provider = StubIdentityProvider(runtime._oidc_settings)

    resp = client.post("/api/v1/auth/oidc/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "authorization_url" in data
    assert "state" in data
    assert "code_verifier" in data
    assert data["authorization_url"].startswith("https://")


def test_api_oidc_callback_success(monkeypatch):
    """OIDC callback с корректными code+state → локальная сессия."""
    monkeypatch.setenv("ATS_OIDC_ENABLED", "true")
    from ats.modules.identity.infra import runtime

    runtime._oidc_settings = OIDCSettings(enabled=True, provider="stub")
    runtime._identity_provider = StubIdentityProvider(runtime._oidc_settings)

    # 1. Start → получаем state + code_verifier
    start_resp = client.post("/api/v1/auth/oidc/start")
    state = start_resp.json()["state"]
    code_verifier = start_resp.json()["code_verifier"]

    # 2. Callback → обмениваем code на сессию
    callback_resp = client.post(
        "/api/v1/auth/oidc/callback",
        json={
            "code": "stub-code-123",
            "state": state,
            "code_verifier": code_verifier,
        },
    )
    assert callback_resp.status_code == 200
    data = callback_resp.json()
    assert "token" in data
    assert "csrf_token" in data
    assert data["role"] == "recruiter"
    assert data["is_new_user"] is False


def test_api_oidc_callback_invalid_state(monkeypatch):
    """OIDC callback с неверным state → 400."""
    monkeypatch.setenv("ATS_OIDC_ENABLED", "true")
    from ats.modules.identity.infra import runtime

    runtime._oidc_settings = OIDCSettings(enabled=True, provider="stub")
    runtime._identity_provider = StubIdentityProvider(runtime._oidc_settings)

    resp = client.post(
        "/api/v1/auth/oidc/callback",
        json={
            "code": "stub-code",
            "state": "nonexistent-state",
            "code_verifier": "some-verifier",
        },
    )
    assert resp.status_code == 400
    assert "OIDC error" in resp.json()["detail"]
