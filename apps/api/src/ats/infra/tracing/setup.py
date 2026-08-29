"""Инициализация OpenTelemetry SDK (JUGO-030).

Единая точка настройки трейсинга для всего приложения (API + воркеры).
Вызывается в начале main.py и cli.py — после setup_logging().

УСТОЙЧИВОСТЬ: если OTel SDK не установлен (dev/stub) — no-op, не падает.
Если OTel включён, но exporter недоступен — трейсы не теряются (best-effort).

WHITEBOX AI: span-атрибуты включают tenant_id, ai_model, ai_tokens —
для прозрачности AI-операций в трейсах Jaeger.

SECURE FIRST: span-атрибуты не содержат ПД (только ID и метрики).
"""

from __future__ import annotations

import logging
from typing import Any

from ats.infra.tracing.settings import settings as tracing_settings

logger = logging.getLogger(__name__)

_HAS_OTEL = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _HAS_OTEL = True
except ImportError:
    trace = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]

# Флаг: был ли уже инициализирован OTel (защита от повторной инициализации)
_initialized = False


def setup_tracing() -> None:
    """Настроить OpenTelemetry трейсинг для всего приложения.

    - Создаёт TracerProvider с Resource (service.name, version, namespace)
    - Настраивает OTLP exporter (gRPC или HTTP) → Jaeger/Tempo
    - Устанавливает глобальный tracer
    - Если OTel не установлен или отключён — no-op
    """
    global _initialized

    if _initialized:
        return

    if not _HAS_OTEL:
        logger.debug("OpenTelemetry SDK not installed — tracing disabled (no-op)")
        return

    if not tracing_settings.enabled:
        logger.debug("Tracing disabled by config (ATS_OTEL_ENABLED=false)")
        return

    _init_otel()
    _initialized = True


def _init_otel() -> None:
    """Внутренняя инициализация OTel SDK."""
    assert trace is not None
    assert Resource is not None
    assert TracerProvider is not None

    # Сборка атрибутов ресурса
    resource_attrs: dict[str, str] = {
        "service.name": tracing_settings.service_name,
        "service.version": tracing_settings.service_version,
        "service.namespace": tracing_settings.service_namespace,
    }

    # Доп. атрибуты из env (key=val,key=val)
    if tracing_settings.resource_attributes:
        for pair in tracing_settings.resource_attributes.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, val = pair.split("=", 1)
                resource_attrs[key.strip()] = val.strip()

    resource = Resource.create(resource_attrs)

    # TracerProvider с сэмплером
    sampler = _build_sampler()

    provider = TracerProvider(resource=resource, sampler=sampler)

    # OTLP exporter
    exporter = _build_exporter()
    if exporter is not None:
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    logger.info(
        "OpenTelemetry tracing enabled: service=%s, exporter=%s, endpoint=%s",
        tracing_settings.service_name,
        tracing_settings.otlp_protocol,
        tracing_settings.otlp_endpoint,
    )


def _build_sampler() -> Any:
    """Построить сэмплер из настроек."""
    try:
        from opentelemetry.sdk.trace.sampling import (
            ALWAYS_ON,
            ParentBased,
            TraceIdRatioBased,
        )

        sampler_name = tracing_settings.traces_sampler.lower()

        if sampler_name == "always_on":
            return ALWAYS_ON
        elif sampler_name == "traceidratio":
            ratio = 1.0
            if tracing_settings.traces_sampler_arg:
                try:
                    ratio = float(
                        tracing_settings.traces_sampler_arg.replace("ratio=", "")
                    )
                except ValueError:
                    pass
            return TraceIdRatioBased(ratio)
        elif sampler_name == "parentbased_always_on":
            return ParentBased(root=ALWAYS_ON)
        elif sampler_name == "parentbased_traceidratio":
            ratio = 1.0
            if tracing_settings.traces_sampler_arg:
                try:
                    ratio = float(
                        tracing_settings.traces_sampler_arg.replace("ratio=", "")
                    )
                except ValueError:
                    pass
            return ParentBased(root=TraceIdRatioBased(ratio))
        else:
            return ParentBased(root=ALWAYS_ON)
    except ImportError:
        return None


def _build_exporter() -> Any:
    """Построить OTLP exporter (gRPC или HTTP)."""
    try:
        if tracing_settings.otlp_protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

        return OTLPSpanExporter(endpoint=tracing_settings.otlp_endpoint)
    except ImportError:
        logger.warning(
            "OTLP exporter not installed — traces will not be exported. "
            "Install opentelemetry-exporter-otlp."
        )
        return None


def get_tracer(name: str = "ats") -> Any:
    """Получить tracer. Если OTel не установлен — возвращает no-op tracer."""
    if _HAS_OTEL and _initialized:
        return trace.get_tracer(name)  # type: ignore[union-attr]

    # No-op tracer (совместимый интерфейс)
    return _NoOpTracer()


class _NoOpSpan:
    """No-op span — совместимый с OTel интерфейс, ничего не делает."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def end(self) -> None:
        pass

    def is_recording(self) -> bool:
        return False


class _NoOpTracer:
    """No-op tracer — совместимый с OTel интерфейс, ничего не делает."""

    def start_as_current_span(
        self,
        name: str,
        context: Any = None,
        kind: Any = None,
        attributes: dict[str, Any] | None = None,
        links: Any = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
        end_on_exit: bool = True,
    ) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()
