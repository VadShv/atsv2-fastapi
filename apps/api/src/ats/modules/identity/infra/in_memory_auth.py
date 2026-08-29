"""In-memory реализации Authenticator и SessionStore для stub/dev-режима.

В stub-режиме: любой email + пароль "demo" → демо-пользователь с ролью recruiter.
Это позволяет разрабатывать UI без реальной БД пользователей.
"""

from __future__ import annotations

from uuid import UUID

from ats.modules.identity.domain.rbac import (
    Permission,
    Role,
    User,
    permissions_for_role,
    scope_for_role,
)
from ats.modules.identity.domain.session import Session
from ats.modules.identity.ports.auth import Authenticator, SessionStore


class InMemoryAuthenticator:
    """Stub-аутентификатор: email + "demo" → демо-пользователь."""

    DEMO_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
    DEMO_PASSWORD = "demo"

    def __init__(self, default_role: str = "recruiter") -> None:
        self._default_role = default_role

    async def authenticate(self, email: str, password: str) -> User | None:
        if password != self.DEMO_PASSWORD:
            return None
        return self._build_demo_user(email)

    def _build_demo_user(self, email: str) -> User:
        role_name = self._default_role
        role = Role(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            tenant_id=self.DEMO_TENANT_ID,
            name=role_name,
            permissions=permissions_for_role(role_name),
            scope=scope_for_role(role_name),
            is_system=True,
        )
        return User(
            id=UUID("00000000-0000-0000-0000-000000000010"),
            tenant_id=self.DEMO_TENANT_ID,
            email=email,
            role=role,
        )


class InMemorySessionStore:
    """Хранит сессии в памяти. Для dev и тестов."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create_session(self, user: User) -> Session:
        requires_2fa = user.role is not None and user.role.name == "admin"
        session = Session.create(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role_name=user.role.name if user.role else "viewer",
            requires_2fa=requires_2fa,
        )
        self._sessions[session.token] = session
        return session

    async def get_session(self, token: str) -> Session | None:
        session = self._sessions.get(token)
        if session is None or session.is_expired:
            return None
        return session

    async def revoke_session(self, token: str) -> None:
        self._sessions.pop(token, None)
