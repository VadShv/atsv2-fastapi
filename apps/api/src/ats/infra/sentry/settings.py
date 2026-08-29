"""Настройки Sentry (JUGO-034).

SECURE FIRST: DSN из env, отправка ПД отключена (send_default_pii=false).
УСТОЙЧИВОСТЬ: если sentry-sdk не установлен — no-op, приложение не падает.

Env-переменные (префикс ATS_SENTRY_):
    ATS_SENTRY_DSN=               — DSN Sentry (пусто = отключено)
    ATS_SENTRY_ENVIRONMENT=dev    — окружение (dev/staging/prod)
    ATS_SENTRY_TRACES_SAMPLE_RATE=0.1 — sample rate для performance (0.0-1.0)
    ATS_SENTRY_SEND_DEFAULT_PII=false — отправлять ли ПД (ВСЕГДА false в проде)
    ATS_SENTRY_MAX_BREADCRUMBS=100 — максимум breadcrumbs в событии
    ATS_SENTRY_ATTACH_STACKTRACE=true — прикреплять stacktrace к логам
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SentrySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATS_SENTRY_", env_file=".env", extra="ignore"
    )

    dsn: str = Field(
        default="",
        description="Sentry DSN (пусто = отключено)",
    )
    environment: str = Field(
        default="dev",
        description="Окружение: dev/staging/prod",
    )
    release: str = Field(
        default="ats-core@0.1.0",
        description="Версия релиза (для группировки ошибок)",
    )
    traces_sample_rate: float = Field(
        default=0.0,
        description="Sample rate для performance monitoring (0.0-1.0)",
    )
    send_default_pii: bool = Field(
        default=False,
        description="Отправлять ли ПД (НИКОГДА не включать в проде)",
    )
    max_breadcrumbs: int = Field(
        default=100,
        description="Максимум breadcrumbs в событии",
    )
    attach_stacktrace: bool = Field(
        default=True,
        description="Прикреплять stacktrace к логам",
    )
    # Алерты в мессенджер (webhook)
    alert_webhook_url: str = Field(
        default="",
        description="Webhook URL для алертов (Telegram/Slack)",
    )
    alert_min_level: str = Field(
        default="ERROR",
        description="Минимальный уровень для алерта: WARNING/ERROR/CRITICAL",
    )


settings = SentrySettings()
