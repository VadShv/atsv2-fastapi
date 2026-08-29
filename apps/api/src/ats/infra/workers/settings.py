"""Настройки Redis (SECURE FIRST: параметры только из env).

Единый источник правды для подключения к Redis: стримы (events), кэш (AI),
arq-очереди воркеров. В dev/stub-режиме Redis может отсутствовать — воркеры
и relay работают в noop-режиме (см. OutboxRelay/EventConsumer).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATS_REDIS_", env_file=".env", extra="ignore"
    )

    url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (redis://host:port/db)",
    )
    # arq: пулы очередей (JUGO-012)
    queue_ai: str = "arq:ai"
    queue_index: str = "arq:index"
    queue_webhooks: str = "arq:webhooks"
    queue_analytics: str = "arq:analytics"
    queue_scheduler: str = "arq:scheduler"
    # job-таймауты (сек)
    job_timeout: int = 300
    # graceful shutdown: сколько ждать завершения активных job (сек)
    shutdown_timeout: int = 30
    # health-check интервал (сек)
    health_check_interval: int = 30


settings = RedisSettings()
