"""FastAPI-зависимости для аутентификации и авторизации (SECURE FIRST).

ТЗ §3.1: deny-by-default. Продуктовый код использует require_permission("..."),
а не захардкоженные проверки ролей.

В stub-режиме (ATS_STUB_MODE=1) — демо-пользователь без реальной аутентификации,
чтобы UI/тесты работали. В prod — opaque-токен из cookie/header или API-ключ.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from ats.modules.identity.domain.api_key import is_api_key
from ats.modules.identity.domain.rbac import (
    Permission,
    Role,
    User,
    permissions_for_role,
    scope_for_role,
)

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


def _extract_token(request: Request | None, authorization: str | None) -> str | None:
    """Извлечь opaque-токен или API-ключ из cookie или Authorization: Bearer."""
    # 1. Cookie (только session token, не API key)
    if request is not None:
        cookie_token = request.cookies.get("ats_session", "")
        if cookie_token:
            return cookie_token
    # 2. Authorization header
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return None


async def _authenticate_api_key(raw_key: str) -> User:
    """Аутентифицировать по API-ключу (jugo_live_*).

    SECURE FIRST: ключ хэшируется и сравнивается с хранилищем.
    Пользователь получает роль api_client с permissions из scopes ключа.
    """
    from ats.modules.identity.domain.api_key import hash_api_key
    from ats.modules.identity.infra.runtime import get_api_key_store

    store = get_api_key_store()
    key_hash = hash_api_key(raw_key)
    api_key = await store.get_by_hash(key_hash)

    if api_key is None or not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или отозванный API-ключ",
        )

    # Обновляем last_used (fire-and-forget)
    await store.update_last_used(api_key.id)

    # Создаём User с permissions из scopes ключа
    permissions = frozenset(Permission(p) for p in api_key.scopes)
    role = Role(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=api_key.tenant_id,
        name="api_client",
        permissions=permissions,
        scope=scope_for_role("api_client"),
        is_system=True,
    )
    return User(
        id=api_key.id,  # используем ID ключа как user_id
        tenant_id=api_key.tenant_id,
        email=f"api-key:{api_key.name}",
        role=role,
    )


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    """Извлечь текущего пользователя из запроса.

    Stub-режим: возвращает демо-пользователя (без проверки токена).
    Prod: парсит opaque-токен из Authorization: Bearer <token> или cookie,
    валидирует через SessionStore. Если токен — API-ключ (jugo_live_*),
    валидирует через ApiKeyStore.
    """
    if os.getenv("ATS_STUB_MODE", "1") == "1":
        return _stub_user()

    token = _extract_token(request, authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация (Bearer token или cookie)",
        )

    # API-ключ (jugo_live_*) → отдельный путь
    if is_api_key(token):
        return await _authenticate_api_key(token)

    # Session token → SessionStore
    from ats.modules.identity.infra.runtime import get_session_store

    session_store = get_session_store()
    session = await session_store.get_session(token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истёкший токен",
        )

    # Восстанавливаем User из сессии
    role_name = session.role_name
    role = Role(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=session.tenant_id,
        name=role_name,
        permissions=permissions_for_role(role_name),
        scope=scope_for_role(role_name),
        is_system=True,
    )
    email = session.metadata.get("email", "unknown@ats.local")
    return User(
        id=session.user_id,
        tenant_id=session.tenant_id,
        email=email,
        role=role,
    )


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
