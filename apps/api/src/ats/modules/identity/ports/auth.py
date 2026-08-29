"""Порт Authenticator + SessionStore (SECURE FIRST).

Аутентификация и управление сессиями. Домен зависит от интерфейса;
реализация (Postgres sessions / Redis) — в infra.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.identity.domain.rbac import User
from ats.modules.identity.domain.session import Session


@runtime_checkable
class Authenticator(Protocol):
    """Порт: аутентификация пользователя по credentials."""

    async def authenticate(self, email: str, password: str) -> User | None:
        """Проверить credentials. None — отказ (deny-by-default)."""
        ...


@runtime_checkable
class SessionStore(Protocol):
    """Порт: хранение и валидация сессий (opaque tokens)."""

    async def create_session(self, user: User) -> Session:
        """Создать сессию для аутентифицированного пользователя."""
        ...

    async def get_session(self, token: str) -> Session | None:
        """Найти сессию по opaque-токену. None — нет/истекла."""
        ...

    async def revoke_session(self, token: str) -> None:
        """Отозвать сессию (logout)."""
        ...
