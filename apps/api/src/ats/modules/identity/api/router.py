"""Auth-роутер: login, logout, refresh, me + 2FA (SECURE FIRST).

ТЗ §15: сессии HttpOnly+Secure+SameSite, CSRF-токены, rate limit,
account lockout, token rotation (refresh), 2FA (TOTP) для админ-ролей.

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
from ats.modules.identity.domain.two_factor import is_2fa_required_for_user
from ats.modules.identity.infra.csrf import CSRF_COOKIE_NAME
from ats.modules.identity.infra.runtime import (
    get_account_lockout,
    get_authenticator,
    get_rate_limiter,
    get_session_store,
    get_two_factor_store,
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


class LoginChallengeResponse(BaseModel):
    """Ответ при логине, когда требуется 2FA."""
    challenge_token: str
    requires_2fa: bool = True
    message: str = "Требуется 2FA-код"


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


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    backup_codes: list[str]


class TwoFactorVerifyRequest(BaseModel):
    code: str


class TwoFactorChallengeVerifyRequest(BaseModel):
    challenge_token: str
    code: str


class TwoFactorBackupRequest(BaseModel):
    challenge_token: str
    backup_code: str


class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    required: bool
    remaining_backup_codes: int


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


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response
) -> LoginResponse | LoginChallengeResponse:
    """Аутентификация по credentials → сессия ИЛИ 2FA-challenge.

    SECURE FIRST:
    - Rate limit: 5 попыток / 5 мин / IP (429 при превышении).
    - Account lockout: блокировка после 5 неудач по email.
    - 2FA: если требуется для роли или включена пользователем → challenge.
    - Не раскрывает, существует ли email (одинаковое сообщение).
    """
    authenticator = get_authenticator()
    session_store = get_session_store()
    rate_limiter = get_rate_limiter()
    lockout = get_account_lockout()
    two_factor_store = get_two_factor_store()

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

    # 5. Проверка 2FA
    role_name = user.role.name if user.role else "viewer"
    tf_config = await two_factor_store.get_config(user.id)
    if is_2fa_required_for_user(role_name, tf_config):
        # Создаём challenge — пользователь должен подтвердить 2FA-код
        challenge = await two_factor_store.create_challenge(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role_name=role_name,
        )
        logger.info("Login requires 2FA: %s (role=%s)", body.email, role_name)
        return LoginChallengeResponse(
            challenge_token=challenge.challenge_token,
        )

    # 6. 2FA не требуется — создаём сессию
    session = await session_store.create_session(user)
    _set_session_cookie(response, session.token, session.csrf_token)

    logger.info("Login success: %s (role=%s)", body.email, session.role_name)

    return LoginResponse(
        token=session.token,
        csrf_token=session.csrf_token,
        role=session.role_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/2fa/verify", response_model=LoginResponse)
async def verify_2fa_challenge(
    body: TwoFactorChallengeVerifyRequest,
    response: Response,
) -> LoginResponse:
    """Завершить вход: проверить 2FA-код для challenge → создать сессию.

    Принимает challenge_token (из login) + TOTP-код.
    """
    two_factor_store = get_two_factor_store()
    session_store = get_session_store()

    challenge = await two_factor_store.get_challenge(body.challenge_token)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Challenge не найден или истёк",
        )

    if not await two_factor_store.verify_code(challenge.user_id, body.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный 2FA-код",
        )

    # 2FA подтверждена — отзываем challenge, создаём сессию
    await two_factor_store.revoke_challenge(body.challenge_token)

    from ats.modules.identity.domain.rbac import (
        Role,
        permissions_for_role,
        scope_for_role,
    )
    from uuid import UUID

    role_name = challenge.role_name
    role = Role(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=challenge.tenant_id,
        name=role_name,
        permissions=permissions_for_role(role_name),
        scope=scope_for_role(role_name),
        is_system=True,
    )
    user = User(
        id=challenge.user_id,
        tenant_id=challenge.tenant_id,
        email="admin@ats.local",  # email из challenge недоступен (opaque)
        role=role,
    )
    session = await session_store.create_session(user)
    _set_session_cookie(response, session.token, session.csrf_token)

    logger.info("2FA login success: user_id=%s", challenge.user_id)

    return LoginResponse(
        token=session.token,
        csrf_token=session.csrf_token,
        role=session.role_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/2fa/backup", response_model=LoginResponse)
async def verify_backup_code(
    body: TwoFactorBackupRequest,
    response: Response,
) -> LoginResponse:
    """Завершить вход через backup-код (одноразовый)."""
    two_factor_store = get_two_factor_store()
    session_store = get_session_store()

    challenge = await two_factor_store.get_challenge(body.challenge_token)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Challenge не найден или истёк",
        )

    if not await two_factor_store.verify_backup_code(
        challenge.user_id, body.backup_code
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или уже использованный backup-код",
        )

    await two_factor_store.revoke_challenge(body.challenge_token)

    from ats.modules.identity.domain.rbac import (
        Role,
        permissions_for_role,
        scope_for_role,
    )
    from uuid import UUID

    role_name = challenge.role_name
    role = Role(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=challenge.tenant_id,
        name=role_name,
        permissions=permissions_for_role(role_name),
        scope=scope_for_role(role_name),
        is_system=True,
    )
    user = User(
        id=challenge.user_id,
        tenant_id=challenge.tenant_id,
        email="admin@ats.local",
        role=role,
    )
    session = await session_store.create_session(user)
    _set_session_cookie(response, session.token, session.csrf_token)

    logger.info("2FA backup-code login: user_id=%s", challenge.user_id)

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


# ---------------------------------------------------------------------------
# 2FA management endpoints (setup, verify, disable, status)
# ---------------------------------------------------------------------------


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    user: User = Depends(get_current_user),
) -> TwoFactorSetupResponse:
    """Настроить 2FA: сгенерировать secret + backup codes.

    Возвращает секрет, otpauth URI (для QR-кода) и backup-коды.
    2FA не включается до вызова /2fa/verify с корректным кодом.
    """
    two_factor_store = get_two_factor_store()
    result = await two_factor_store.setup(
        user_id=user.id,
        tenant_id=user.tenant_id,
        issuer="ATS Jugo",
        account=user.email,
    )
    logger.info("2FA setup: user_id=%s", user.id)
    return TwoFactorSetupResponse(
        secret=result.secret,
        otpauth_uri=result.otpauth_uri,
        backup_codes=result.backup_codes,
    )


@router.post("/2fa/enable", response_model=TwoFactorStatusResponse)
async def enable_2fa(
    body: TwoFactorVerifyRequest,
    user: User = Depends(get_current_user),
) -> TwoFactorStatusResponse:
    """Подтвердить setup и включить 2FA (verify TOTP-код)."""
    two_factor_store = get_two_factor_store()
    success = await two_factor_store.verify_and_enable(user.id, body.code)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный 2FA-код",
        )
    config = await two_factor_store.get_config(user.id)
    return TwoFactorStatusResponse(
        enabled=True,
        required=is_2fa_required_for_user(
            user.role.name if user.role else "viewer", config
        ),
        remaining_backup_codes=config.remaining_backup_codes()
        if config
        else 0,
    )


@router.get("/2fa/status", response_model=TwoFactorStatusResponse)
async def status_2fa(
    user: User = Depends(get_current_user),
) -> TwoFactorStatusResponse:
    """Статус 2FA для текущего пользователя."""
    two_factor_store = get_two_factor_store()
    config = await two_factor_store.get_config(user.id)
    role_name = user.role.name if user.role else "viewer"
    return TwoFactorStatusResponse(
        enabled=config.enabled if config else False,
        required=is_2fa_required_for_user(role_name, config),
        remaining_backup_codes=config.remaining_backup_codes()
        if config
        else 0,
    )


@router.post("/2fa/disable", response_model=TwoFactorStatusResponse)
async def disable_2fa(
    body: TwoFactorVerifyRequest,
    user: User = Depends(get_current_user),
) -> TwoFactorStatusResponse:
    """Отключить 2FA (требуется TOTP-код для подтверждения).

    SECURE FIRST: нельзя отключить 2FA без подтверждения кодом.
    """
    two_factor_store = get_two_factor_store()
    if not await two_factor_store.verify_code(user.id, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный 2FA-код",
        )
    await two_factor_store.disable(user.id)
    role_name = user.role.name if user.role else "viewer"
    return TwoFactorStatusResponse(
        enabled=False,
        required=is_2fa_required_for_user(role_name, None),
        remaining_backup_codes=0,
    )
