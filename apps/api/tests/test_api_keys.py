"""Тесты API-ключей: генерация, хэш-хранение, скоупы, CRUD, auth (JUGO-025).

SECURE FIRST: проверяем что ключи хранятся только как хэши, raw_key
возвращается один раз, скоупы ограничивают доступ.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ats.main import app
from ats.modules.identity.domain.api_key import (
    KEY_PREFIX,
    ApiKey,
    generate_api_key,
    hash_api_key,
    is_api_key,
)
from ats.modules.identity.infra.in_memory_api_key import InMemoryApiKeyStore
from ats.modules.identity.infra.runtime import get_api_key_store

from uuid import UUID

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
client = TestClient(app)


# ---------------------------------------------------------------------------
# Генерация и хэширование — unit-тесты
# ---------------------------------------------------------------------------


def test_generate_api_key_format():
    raw_key, key_hash = generate_api_key()
    assert raw_key.startswith(KEY_PREFIX)
    assert len(raw_key) > len(KEY_PREFIX) + 20  # есть случайная часть
    assert key_hash != raw_key
    assert len(key_hash) == 64  # SHA-256 hex


def test_generate_api_key_unique():
    k1, _ = generate_api_key()
    k2, _ = generate_api_key()
    assert k1 != k2


def test_hash_api_key_deterministic():
    raw_key, _ = generate_api_key()
    h1 = hash_api_key(raw_key)
    h2 = hash_api_key(raw_key)
    assert h1 == h2


def test_hash_api_key_not_reversible():
    raw_key, _ = generate_api_key()
    h = hash_api_key(raw_key)
    assert raw_key not in h
    # Хэш не содержит префикса
    assert KEY_PREFIX not in h


def test_is_api_key_detects_prefix():
    raw_key, _ = generate_api_key()
    assert is_api_key(raw_key) is True
    assert is_api_key("some-session-token") is False
    assert is_api_key("") is False


# ---------------------------------------------------------------------------
# ApiKey domain model — unit-тесты
# ---------------------------------------------------------------------------


def test_api_key_create_active():
    _, key_hash = generate_api_key()
    key = ApiKey.create(
        tenant_id=TENANT_ID,
        key_hash=key_hash,
        name="Test key",
        scopes=frozenset(["candidate:read", "application:read"]),
    )
    assert key.is_active is True
    assert key.is_revoked is False
    assert key.is_expired is False
    assert key.has_scope("candidate:read") is True
    assert key.has_scope("vacancy:create") is False  # deny-by-default


def test_api_key_revoked_not_active():
    from datetime import datetime, timezone

    _, key_hash = generate_api_key()
    key = ApiKey(
        id=UUID(int=1),
        tenant_id=TENANT_ID,
        key_hash=key_hash,
        name="Revoked",
        scopes=frozenset(["candidate:read"]),
        created_at=datetime.now(timezone.utc),
        revoked_at=datetime.now(timezone.utc),
    )
    assert key.is_active is False
    assert key.is_revoked is True


def test_api_key_expired_not_active():
    from datetime import timedelta

    from datetime import datetime, timezone

    _, key_hash = generate_api_key()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    key = ApiKey(
        id=UUID(int=1),
        tenant_id=TENANT_ID,
        key_hash=key_hash,
        name="Expired",
        scopes=frozenset(["candidate:read"]),
        created_at=past - timedelta(days=365),
        expires_at=past,
    )
    assert key.is_active is False
    assert key.is_expired is True


# ---------------------------------------------------------------------------
# InMemoryApiKeyStore — unit-тесты
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_create_and_get_by_hash():
    store = InMemoryApiKeyStore()
    result = await store.create_key(
        tenant_id=TENANT_ID,
        name="Slack integration",
        scopes=frozenset(["candidate:read"]),
    )
    assert result.raw_key.startswith(KEY_PREFIX)

    # Найти по хэшу
    key_hash = hash_api_key(result.raw_key)
    found = await store.get_by_hash(key_hash)
    assert found is not None
    assert found.name == "Slack integration"
    assert found.is_active is True


@pytest.mark.asyncio
async def test_store_get_by_hash_not_found():
    store = InMemoryApiKeyStore()
    found = await store.get_by_hash("nonexistent-hash")
    assert found is None


@pytest.mark.asyncio
async def test_store_get_by_id():
    store = InMemoryApiKeyStore()
    result = await store.create_key(
        tenant_id=TENANT_ID,
        name="Test",
        scopes=frozenset(["candidate:read"]),
    )
    found = await store.get_by_id(result.api_key.id)
    assert found is not None
    assert found.id == result.api_key.id


@pytest.mark.asyncio
async def test_store_list_keys():
    store = InMemoryApiKeyStore()
    await store.create_key(
        tenant_id=TENANT_ID,
        name="Key 1",
        scopes=frozenset(["candidate:read"]),
    )
    await store.create_key(
        tenant_id=TENANT_ID,
        name="Key 2",
        scopes=frozenset(["application:read"]),
    )
    # Другой тенант
    other_tenant = UUID("00000000-0000-0000-0000-000000000002")
    await store.create_key(
        tenant_id=other_tenant,
        name="Other tenant key",
        scopes=frozenset(["candidate:read"]),
    )

    keys = await store.list_keys(TENANT_ID)
    assert len(keys) == 2
    # ApiKeyInfo не содержит raw_key и key_hash
    for k in keys:
        assert not hasattr(k, "raw_key")
        assert not hasattr(k, "key_hash")


@pytest.mark.asyncio
async def test_store_revoke_key():
    store = InMemoryApiKeyStore()
    result = await store.create_key(
        tenant_id=TENANT_ID,
        name="To revoke",
        scopes=frozenset(["candidate:read"]),
    )
    success = await store.revoke_key(result.api_key.id)
    assert success is True

    found = await store.get_by_id(result.api_key.id)
    assert found.is_active is False
    assert found.is_revoked is True


@pytest.mark.asyncio
async def test_store_revoke_not_found():
    store = InMemoryApiKeyStore()
    success = await store.revoke_key(UUID(int=999))
    assert success is False


@pytest.mark.asyncio
async def test_store_update_last_used():
    store = InMemoryApiKeyStore()
    result = await store.create_key(
        tenant_id=TENANT_ID,
        name="Test",
        scopes=frozenset(["candidate:read"]),
    )
    assert result.api_key.last_used_at is None
    await store.update_last_used(result.api_key.id)
    found = await store.get_by_id(result.api_key.id)
    assert found.last_used_at is not None


# ---------------------------------------------------------------------------
# API CRUD — integration через TestClient (stub-режим)
# ---------------------------------------------------------------------------


def test_api_create_api_key():
    resp = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Slack", "scopes": ["candidate:read", "application:read"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_key"].startswith(KEY_PREFIX)
    assert data["name"] == "Slack"
    assert set(data["scopes"]) == {"candidate:read", "application:read"}


def test_api_list_api_keys():
    client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Key A", "scopes": ["candidate:read"]},
    )
    client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Key B", "scopes": ["application:read"]},
    )
    resp = client.get("/api/v1/auth/api-keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 2
    # raw_key не возвращается в списке
    for k in keys:
        assert "raw_key" not in k


def test_api_revoke_api_key():
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "To revoke", "scopes": ["candidate:read"]},
    )
    key_id = create_resp.json()["key_id"]

    resp = client.delete(f"/api/v1/auth/api-keys/{key_id}")
    assert resp.status_code == 204

    # Проверяем что отозван
    list_resp = client.get("/api/v1/auth/api-keys")
    keys = list_resp.json()
    revoked = [k for k in keys if k["key_id"] == key_id]
    assert len(revoked) == 1
    assert revoked[0]["is_active"] is False


def test_api_revoke_not_found():
    resp = client.delete("/api/v1/auth/api-keys/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


def test_api_revoke_invalid_uuid():
    resp = client.delete("/api/v1/auth/api-keys/not-a-uuid")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Auth по API-ключу — требует отключения stub-режима
# ---------------------------------------------------------------------------


def test_api_key_auth_success(monkeypatch):
    """Аутентификация по API-ключу → 200 /me (prod-режим)."""
    monkeypatch.setenv("ATS_STUB_MODE", "0")

    # Создаём ключ (в stub-режиме для удобства, потом переключаем)
    monkeypatch.setenv("ATS_STUB_MODE", "1")
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Auth test", "scopes": ["candidate:read"]},
    )
    raw_key = create_resp.json()["raw_key"]

    # Переключаем в prod-режим и делаем запрос с API-ключом
    monkeypatch.setenv("ATS_STUB_MODE", "0")
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "api_client"
    assert data["email"].startswith("api-key:")


def test_api_key_auth_revoked_rejected(monkeypatch):
    """Отозванный API-ключ → 401."""
    monkeypatch.setenv("ATS_STUB_MODE", "1")
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Revoke test", "scopes": ["candidate:read"]},
    )
    raw_key = create_resp.json()["raw_key"]
    key_id = create_resp.json()["key_id"]

    # Отзываем
    client.delete(f"/api/v1/auth/api-keys/{key_id}")

    # Пробуем авторизоваться
    monkeypatch.setenv("ATS_STUB_MODE", "0")
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401


def test_api_key_auth_invalid_rejected(monkeypatch):
    """Несуществующий API-ключ → 401."""
    monkeypatch.setenv("ATS_STUB_MODE", "0")
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer jugo_live_nonexistent_key_12345"},
    )
    assert resp.status_code == 401
