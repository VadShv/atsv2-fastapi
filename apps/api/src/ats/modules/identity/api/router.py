"""Auth-роутер: login, logout, refresh, me (SECURE FIRST).

ТЗ §15: сессии HttpOnly+Secure+SameSite, CSRF-токены, rate limit,
account lockout, token rotation (refresh).

В stub-режиме — упрощённый логин (email + "demo").
"""

from __future__ import annotations

import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator

from ats.modules.identity.api.deps import get_current_user
from ats.modules.identity.domain.rbac import User
from ats.modules.identity.infra.csrf import CSRF_COOKIE_NAME
from ats.modules.identity.infra.runtime import (
    get_account_lockout,
    get_authenticator,
    get_rate_limiter,
    get_session_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

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


class RefreshResponse(BaseModel):
    token: str
    csrf_token: str
    role: str
    expires_at: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    role: str
    tenant_id: str


def _client_ip(request: Request) -> str:
    """Определить IP клиента (X-Forwarded-For или request.client.host)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookie(
    response: Response, token: str, csrf_token: str
) -> None:
    """Установить cookies: ats_session (HttpOnly) + ats_csrf (JS-readable)."""
    secure = os.getenv("ATS_STUB_MODE", "1") != "1"
    response.set_cookie(
        key="ats_session",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=28800,  # 8 часов
    )
    # CSRF-токен: JS может читать (double-submit pattern)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=28800,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, request: Request, response: Response
) -> LoginResponse:
    """Аутентификация по credentials → opaque-токен сессии.

    SECURE FIRST:
    - Rate limit: 5 попыток / 5 мин / IP (429 при превышении).
    - Account lockout: блокировка после 5 неудач по email.
    - Не раскрывает, существует ли email (одинаковое сообщение).
    """
    authenticator = get_authenticator()
    session_store = get_session_store()
    rate_limiter = get_rate_limiter()
    lockout = get_account_lockout()

    ip = _client_ip(request)

    # 1. Проверка блокировки аккаунта
    if lockout.is_locked(body.email):
        logger.warning("Login blocked (account locked): %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много неудачных попыток. Попробуйте позже.",
        )

    # 2. Проверка rate limit по IP
    if rate_limiter.is_rate_limited(ip):
        logger.warning("Login rate limited: %s", ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Попробуйте позже.",
        )

    # 3. Аутентификация
    user = await authenticator.authenticate(body.email, body.password)

    # Фиксируем попытку (для rate limit) — до проверки результата
    rate_limiter.record_attempt(ip)

    if user is None:
        # Фиксируем неудачу для account lockout
        lockout.record_failure(body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    # 4. Успешный вход — сбрасываем счётчики
    rate_limiter.reset(ip)
    lockout.record_success(body.email)

    session = await session_store.create_session(user)

    _set_session_cookie(response, session.token, session.csrf_token)

    logger.info("Login success: %s (role=%s)", body.email, session.role_name)

    return LoginResponse(
        token=session.token,
        csrf_token=session.csrf_token,
        role=session.role_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request, response: Response
) -> RefreshResponse:
    """Продлить сессию: token rotation (старый токен отзывается).

    SECURE FIRST: старый токен становится недействительным,
    выдаётся новый с новым CSRF-токеном.
    """
    session_store = get_session_store()

    # Токен из cookie или заголовка
    token = request.cookies.get("ats_session", "")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется активная сессия",
        )

    new_session = await session_store.refresh_session(token)
    if new_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия не найдена или истекла",
        )

    _set_session_cookie(response, new_session.token, new_session.csrf_token)

    logger.info(
        "Session refreshed: user_id=%s", new_session.user_id
    )

    return RefreshResponse(
        token=new_session.token,
        csrf_token=new_session.csrf_token,
        role=new_session.role_name,
        expires_at=new_session.expires_at.isoformat(),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response
) -> None:
    """Отозвать сессию (logout)."""
    session_store = get_session_store()

    token = request.cookies.get("ats_session", "")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()

    if token:
        await session_store.revoke_session(token)

    response.delete_cookie("ats_session")
    response.delete_cookie(CSRF_COOKIE_NAME)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    """Текущий аутентифицированный пользователь."""
    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role.name if user.role else "viewer",
        tenant_id=str(user.tenant_id),
    )
