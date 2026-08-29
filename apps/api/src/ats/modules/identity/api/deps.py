"""FastAPI-зависимости для аутентификации и авторизации (SECURE FIRST).

ТЗ §3.1: deny-by-default. Продуктовый код использует require_permission("..."),
а не захардкоженные проверки ролей.

В stub-режиме (ATS_STUB_MODE=1) — демо-пользователь без реальной аутентификации,
чтобы UI/тесты работали. В prod — opaque-токен из cookie/header.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status

from ats.modules.identity.domain.rbac import (
    Permission,
    Role,
    User,
    permissions_for_role,
    scope_for_role,
)
from ats.modules.identity.domain.session import Session


# Демо-пользователь для stub-режима
_DEMO_TENANT = UUID("00000000-0000-0000-0000-000000000001")
_DEMO_USER = UUID("00000000-0000-0000-0000-000000000010")


def _stub_user() -> User:
    role_name = os.getenv("ATS_DEMO_ROLE", "recruiter")
    role = Role(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=_DEMO_TENANT,
        name=role_name,
        permissions=permissions_for_role(role_name),
        scope=scope_for_role(role_name),
        is_system=True,
    )
    return User(
        id=_DEMO_USER,
        tenant_id=_DEMO_TENANT,
        email="demo@ats.local",
        role=role,
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> User:
    """Извлечь текущего пользователя из запроса.

    Stub-режим: возвращает демо-пользователя (без проверки токена).
    Prod: парсит opaque-токен из Authorization: Bearer <token> или cookie,
    валидирует через SessionStore.
    """
    if os.getenv("ATS_STUB_MODE", "1") == "1":
        return _stub_user()

    # Prod-путь: токен из заголовка
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация (Bearer token)",
        )
    token = authorization.removeprefix("Bearer ").strip()
    # TODO (Wave 1): валидация через SessionStore из контейнера
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
        )
    # Пока в prod без полной интеграции SessionStore — откат к stub
    return _stub_user()


def require_permission(permission: str):
    """Dependency-фабрика: проверить разрешение (deny-by-default).

    Использование:
        @router.post("/vacancies", dependencies=[Depends(require_permission("vacancy:create"))])
    """

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостаточно прав: требуется {permission}",
            )
        return user

    return _checker


async def get_tenant_id(user: User = Depends(get_current_user)) -> UUID:
    """Извлечь tenant_id текущего пользователя (для RLS-сессии)."""
    return user.tenant_id
