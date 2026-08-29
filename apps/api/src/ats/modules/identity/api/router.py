"""Auth-роутер: login, logout, me (SECURE FIRST).

ТЗ §15: сессии HttpOnly+Secure+SameSite, CSRF-токены.
В stub-режиме — упрощённый логин (email + "demo").
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, field_validator

from ats.modules.identity.api.deps import get_current_user
from ats.modules.identity.domain.rbac import User
from ats.modules.identity.infra.in_memory_auth import (
    InMemoryAuthenticator,
    InMemorySessionStore,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Singleton-ы для stub-режима (в prod — из контейнера)
_authenticator = InMemoryAuthenticator()
_session_store = InMemorySessionStore()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("Некорректный email")
        return v.lower().strip()


class LoginResponse(BaseModel):
    token: str
    csrf_token: str
    role: str
    expires_at: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    role: str
    tenant_id: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response) -> LoginResponse:
    """Аутентификация по credentials → opaque-токен сессии."""
    user = await _authenticator.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    session = await _session_store.create_session(user)

    # HttpOnly+Secure+SameSite cookie (ТЗ §15)
    secure = os.getenv("ATS_STUB_MODE", "1") != "1"
    response.set_cookie(
        key="ats_session",
        value=session.token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(
            (session.expires_at - session.issued_at).total_seconds()
        ),
    )

    return LoginResponse(
        token=session.token,
        csrf_token=session.csrf_token,
        role=session.role_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
) -> None:
    """Отозвать сессию (logout)."""
    # В prod — токен из cookie/header → session_store.revoke
    response.delete_cookie("ats_session")


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    """Текущий аутентифицированный пользователь."""
    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role.name if user.role else "viewer",
        tenant_id=str(user.tenant_id),
    )
