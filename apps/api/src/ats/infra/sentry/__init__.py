"""Sentry + алерты (JUGO-034).

Перехват ошибок backend, отправка в Sentry + webhook алерты в мессенджер.
Ленивый импорт sentry-sdk: если не установлен — no-op.

- setup_sentry() — инициализация Sentry SDK (вызывается в main.py)
- SentryMiddleware — перехват 5xx + отправка в Sentry + webhook
- capture_exception() / capture_message() — ручная отправка событий
- send_alert() — webhook алерт в Telegram/Slack
"""

from ats.infra.sentry.alerts import send_alert, send_alert_sync
from ats.infra.sentry.middleware import SentryMiddleware
from ats.infra.sentry.settings import settings as sentry_settings
from ats.infra.sentry.setup import (
    capture_exception,
    capture_message,
    is_sentry_enabled,
    set_user_context,
    setup_sentry,
)

__all__ = [
    "setup_sentry",
    "is_sentry_enabled",
    "SentryMiddleware",
    "capture_exception",
    "capture_message",
    "set_user_context",
    "send_alert",
    "send_alert_sync",
    "sentry_settings",
]
