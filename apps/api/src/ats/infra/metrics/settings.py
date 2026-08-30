"""Настройки метрик Prometheus (JUGO-031).

УСТОЙЧИВОСТЬ: prometheus_client может быть не установлен (dev/stub) —
все импорты ленивые, fallback на no-op счётчики.

Env-переменные (префикс ATS_METRICS_):
    ATS_METRICS_ENABLED=true        — включить сбор метрик
    ATS_METRICS_PATH=/metrics       — путь endpoint'а
    ATS_METRICS_INCLUDE_ENDPOINTS=true — включать endpoint в метрики
    ATS_METRICS_GROUP_STATUS_CODES=true — группировать по status code
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetricsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATS_METRICS_", env_file=".env", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Включить сбор Prometheus-метрик (false = no-op)",
    )
    path: str = Field(
        default="/metrics",
        description="Путь HTTP endpoint'а для scrape",
    )
    include_endpoints: bool = Field(
        default=True,
        description="Включать handler в метрики (false = только агрегаты)",
    )
    group_status_codes: bool = Field(
        default=True,
        description="Группировать по HTTP status code (2xx/4xx/5xx)",
    )
    latency_buckets: str = Field(
        default="0.005,0.01,0.025,0.05,0.1,0.25,0.5,1,2.5,5,10",
        description="Buckets для histogram латентностей (секунды)",
    )


settings = MetricsSettings()
