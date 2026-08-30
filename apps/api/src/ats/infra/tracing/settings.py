"""Настройки трейсинга OpenTelemetry (JUGO-030).

УСТОЙЧИВОСТЬ: OTel может быть не установлен (dev/stub) — все импорты ленивые.
SECURE FIRST: трейс-сэмплинг не логирует ПД, только span-метаданные.

Env-переменные (префикс ATS_OTEL_):
    ATS_OTEL_ENABLED=true          — включить OTel экспорт
    ATS_OTEL_SERVICE_NAME=ats-core — имя сервиса в Jaeger
    ATS_OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317 — endpoint OTLP gRPC
    ATS_OTEL_RESOURCE_ATTRIBUTES=  — доп. атрибуты ресурса (key=val,key=val)
    ATS_OTEL_TRACES_SAMPLER=parentbased_always_on — стратегия сэмплинга
    ATS_OTEL_TRACES_SAMPLER_ARG=   — аргумент сэмплера (напр. ratio=0.1)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TracingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATS_OTEL_", env_file=".env", extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Включить OTel экспорт трейсов (false = no-op, для dev/stub)",
    )
    service_name: str = Field(
        default="ats-core",
        description="Имя сервиса в Jaeger/Tempo",
    )
    service_version: str = Field(
        default="0.1.0",
        description="Версия сервиса (атрибут ресурса)",
    )
    service_namespace: str = Field(
        default="ats",
        description="Namespace сервиса (атрибут ресурса)",
    )
    otlp_endpoint: str = Field(
        default="http://jaeger:4317",
        description="Endpoint OTLP gRPC экспортёра (Jaeger/Tempo)",
    )
    otlp_protocol: str = Field(
        default="grpc",
        description="Протокол OTLP: grpc или http/protobuf",
    )
    resource_attributes: str = Field(
        default="",
        description="Доп. атрибуты ресурса: key=val,key=val",
    )
    traces_sampler: str = Field(
        default="parentbased_always_on",
        description="Стратегия сэмплинга трейсов",
    )
    traces_sampler_arg: str = Field(
        default="",
        description="Аргумент сэмплера (напр. ratio=0.1 для traceidratio)",
    )
    propagate_to_workers: bool = Field(
        default=True,
        description="Прокидывать trace_context в воркеры (W3C traceparent)",
    )


settings = TracingSettings()
