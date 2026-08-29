"""Инициализация Sentry SDK (JUGO-034).

УСТОЙЧИВОСТЬ: если sentry-sdk не установлен или DSN пустой — no-op.
SECURE FIRST: send_default_pii=false по умолчанию (ПД не отправляется).

Вызывается в начале main.py и cli.py — после setup_logging() и setup_tracing().
"""

from __future__ import annotations

import logging
from typing import Any

from ats.infra.sentry.settings import settings as sentry_settings

logger = logging.getLogger(__name__)

_HAS_SENTRY = False
try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    _HAS_SENTRY = True
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
    FastApiIntegration = None  # type: ignore[assignment]
    StarletteIntegration = None  # type: ignore[assignment]

_initialized = False


def setup_sentry() -> None:
    """Настроить Sentry SDK для всего приложения.

    - Если sentry-sdk не установлен — no-op
    - Если DSN пустой — no-op
    - Иначе: init с integrations (FastAPI/Starlette), environment, release
    """
    global _initialized

    if _initialized:
        return

    if not _HAS_SENTRY:
        logger.debug("sentry-sdk not installed — Sentry disabled (no-op)")
        return

    if not sentry_settings.dsn:
        logger.debug("Sentry DSN not set — Sentry disabled")
        return

    _init_sentry()
    _initialized = True


def _init_sentry() -> None:
    """Внутренняя инициализация Sentry SDK."""
    assert sentry_sdk is not None

    integrations: list[Any] = []

    # FastAPI/Starlette integration (если доступны)
    if StarletteIntegration is not None:
        integrations.append(StarletteIntegration())
    if FastApiIntegration is not None:
        integrations.append(FastApiIntegration())

    sentry_sdk.init(
        dsn=sentry_settings.dsn,
        environment=sentry_settings.environment,
        release=sentry_settings.release,
        traces_sample_rate=sentry_settings.traces_sample_rate,
        send_default_pii=sentry_settings.send_default_pii,
        max_breadcrumbs=sentry_settings.max_breadcrumbs,
        attach_stacktrace=sentry_settings.attach_stacktrace,
        integrations=integrations,
    )

    logger.info(
        "Sentry initialized: env=%s, release=%s, traces_sample_rate=%s",
        sentry_settings.environment,
        sentry_settings.release,
        sentry_settings.traces_sample_rate,
    )


def is_sentry_enabled() -> bool:
    """Проверить, активен ли Sentry."""
    return _HAS_SENTRY and _initialized and bool(sentry_settings.dsn)


def capture_exception(exc: Exception, **context: Any) -> None:
    """Отправить исключение в Sentry (best-effort, не падает).

    Args:
        exc: исключение для отправки.
        **context: доп. контекст (tags, extra, user).
    """
    if not is_sentry_enabled():
        logger.error("Exception (Sentry disabled): %s", exc, exc_info=True)
        return

    assert sentry_sdk is not None

    try:
        with sentry_sdk.push_scope() as scope:
            # Tags
            tags = context.get("tags", {})
            for key, val in tags.items():
                scope.set_tag(key, val)

            # Extra context
            extra = context.get("extra", {})
            for key, val in extra.items():
                scope.set_extra(key, val)

            # User
            user = context.get("user")
            if user:
                scope.set_user(user)

            # Level
            level = context.get("level", "error")
            scope.set_level(level)

            sentry_sdk.capture_exception(exc)
    except Exception:
        logger.error("Failed to send exception to Sentry: %s", exc, exc_info=True)


def capture_message(
    message: str,
    level: str = "info",
    **context: Any,
) -> None:
    """Отправить сообщение в Sentry (best-effort).

    Args:
        message: текст сообщения.
        level: уровень (info/warning/error/fatal).
        **context: доп. контекст (tags, extra).
    """
    if not is_sentry_enabled():
        return

    assert sentry_sdk is not None

    try:
        with sentry_sdk.push_scope() as scope:
            tags = context.get("tags", {})
            for key, val in tags.items():
                scope.set_tag(key, val)

            extra = context.get("extra", {})
            for key, val in extra.items():
                scope.set_extra(key, val)

            scope.set_level(level)
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def set_user_context(
    *,
    user_id: str | None = None,
    tenant_id: str | None = None,
    email: str | None = None,
) -> None:
    """Установить контекст пользователя в Sentry (для атрибуции ошибок).

    SECURE FIRST: email не отправляется если send_default_pii=false.
    """
    if not is_sentry_enabled():
        return

    assert sentry_sdk is not None

    try:
        user_data: dict[str, Any] = {"id": user_id or "anonymous"}
        if tenant_id:
            user_data["tenant_id"] = tenant_id
        if email and sentry_settings.send_default_pii:
            user_data["email"] = email

        sentry_sdk.set_user(user_data)
    except Exception:
        pass
