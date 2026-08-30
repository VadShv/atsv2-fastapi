"""Тесты RBAC и аутентификации (SECURE FIRST, deny-by-default)."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ats.main import app
from ats.modules.identity.domain.rbac import (
    Permission,
    Role,
    User,
    permissions_for_role,
    scope_for_role,
)
from ats.modules.identity.infra.in_memory_auth import (
    InMemoryAuthenticator,
    InMemorySessionStore,
)

TENANT = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Permission / Role
# ---------------------------------------------------------------------------


def test_permission_format():
    p = Permission("vacancy:create")
    assert p.resource == "vacancy"
    assert p.action == "create"


def test_permission_invalid_raises():
    with pytest.raises(ValueError):
        Permission("invalid")


def test_role_deny_by_default():
    role = Role(id=UUID(int=1), tenant_id=TENANT, name="x", permissions=frozenset())
    assert not role.has_permission("vacancy:create")


def test_role_has_permission():
    perms = frozenset([Permission("vacancy:create"), Permission("candidate:read")])
    role = Role(id=UUID(int=1), tenant_id=TENANT, name="x", permissions=perms)
    assert role.has_permission("vacancy:create")
    assert role.has_permission("candidate:read")
    assert not role.has_permission("vacancy:delete")


def test_user_without_role_denied():
    user = User(id=UUID(int=2), tenant_id=TENANT, email="x@y.z", role=None)
    assert not user.has_permission("vacancy:read")


def test_user_inactive_denied():
    role = Role(
        id=UUID(int=1),
        tenant_id=TENANT,
        name="x",
        permissions=frozenset([Permission("vacancy:read")]),
    )
    user = User(id=UUID(int=2), tenant_id=TENANT, email="x@y.z", role=role, is_active=False)
    assert not user.has_permission("vacancy:read")


# ---------------------------------------------------------------------------
# Системные роли-пресеты
# ---------------------------------------------------------------------------


def test_system_role_presets_exist():
    from ats.modules.identity.domain.rbac import SYSTEM_ROLE_PRESETS

    expected = {
        "admin",
        "head_of_recruiting",
        "recruiter",
        "sourcer",
        "hiring_manager",
        "viewer",
        "api_client",
    }
    assert set(SYSTEM_ROLE_PRESETS.keys()) == expected


def test_recruiter_permissions():
    perms = permissions_for_role("recruiter")
    assert Permission("vacancy:create") in perms
    assert Permission("screening:run") in perms
    # Recruiter не может управлять ролями (deny-by-default)
    assert Permission("role:manage") not in perms


def test_admin_has_wildcard():
    perms = permissions_for_role("admin")
    assert Permission("*:*") in perms


def test_hiring_manager_limited():
    perms = permissions_for_role("hiring_manager")
    assert Permission("application:decide") in perms
    # HM не может создавать вакансии
    assert Permission("vacancy:create") not in perms


def test_scope_for_role():
    assert scope_for_role("admin").value == "all"
    assert scope_for_role("recruiter").value == "own"


def test_unknown_role_empty_permissions():
    assert permissions_for_role("nonexistent") == frozenset()


# ---------------------------------------------------------------------------
# InMemoryAuthenticator + SessionStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticator_demo_login():
    auth = InMemoryAuthenticator()
    user = await auth.authenticate("recruiter@ats.local", "demo")
    assert user is not None
    assert user.email == "recruiter@ats.local"
    assert user.role is not None
    assert user.role.name == "recruiter"
    assert user.has_permission("vacancy:create")


@pytest.mark.asyncio
async def test_authenticator_wrong_password():
    auth = InMemoryAuthenticator()
    user = await auth.authenticate("x@y.z", "wrong")
    assert user is None


@pytest.mark.asyncio
async def test_session_store_create_and_get():
    auth = InMemoryAuthenticator()
    store = InMemorySessionStore()
    user = await auth.authenticate("x@y.z", "demo")
    session = await store.create_session(user)
    assert session.token
    fetched = await store.get_session(session.token)
    assert fetched is not None
    assert fetched.user_id == user.id


@pytest.mark.asyncio
async def test_session_store_revoke():
    auth = InMemoryAuthenticator()
    store = InMemorySessionStore()
    user = await auth.authenticate("x@y.z", "demo")
    session = await store.create_session(user)
    await store.revoke_session(session.token)
    assert await store.get_session(session.token) is None


@pytest.mark.asyncio
async def test_admin_session_requires_2fa():
    auth = InMemoryAuthenticator(default_role="admin")
    store = InMemorySessionStore()
    user = await auth.authenticate("admin@ats.local", "demo")
    session = await store.create_session(user)
    assert session.requires_2fa is True


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------


client = TestClient(app)


def test_auth_login_demo():
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@ats.local", "password": "demo"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "csrf_token" in data
    assert data["role"] == "recruiter"


def test_auth_login_wrong_password():
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@ats.local", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_auth_me_in_stub_mode():
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "demo@ats.local"
    assert data["role"] == "recruiter"


def test_auth_logout():
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
