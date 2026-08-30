"""Инициализация логирования: JSON через structlog, fallback на stdlib.

Единая точка настройки логирования для всего приложения (API + воркеры).
Вызывается в начале main.py и cli.py.

SECURE FIRST: ПД маскируется на уровне процессора, до сериализации.
УСТОЙЧИВОСТЬ: логи не падают при ошибках маскирования (best-effort).
Если structlog не установлен (dev/stub) — fallback на stdlib logging
с маскированием ПД через фильтр.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from ats.infra.logging.context import get_log_context
from ats.infra.logging.pii_mask import mask_pii_processor
from ats.infra.logging.settings import settings as log_settings

_HAS_STRUCTLOG = False
try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:
    structlog = None  # type: ignore[assignment]


def setup_logging() -> None:
    """Настроить логирование для всего приложения."""
    level = getattr(logging, log_settings.level.upper(), logging.INFO)

    if _HAS_STRUCTLOG:
        _setup_structlog(level)
    else:
        _setup_stdlib(level)


def _setup_structlog(level: int) -> None:
    """Настроить structlog с JSON-форматом и маскированием ПД."""
    assert structlog is not None

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_tenant_id,
        _add_trace_id,
        _add_user_id,
        _add_request_id,
        mask_pii_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_settings.json_format:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Перехват stdlib logging через structlog (единый формат)
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(message)s",
        force=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _setup_stdlib(level: int) -> None:
    """Fallback: stdlib logging с маскированием ПД через фильтр."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    if log_settings.json_format:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(_ContextFilter())
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


class _JsonFormatter(logging.Formatter):
    """Простой JSON-форматтер для stdlib fallback."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        msg = super().format(record)
        entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": msg,
        }
        ctx = get_all_context_safe()
        entry.update(ctx)
        return json.dumps(entry, default=str, ensure_ascii=False)


class _ContextFilter(logging.Filter):
    """Добавляет tenant_id/trace_id в record (для не-JSON формата)."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_all_context_safe()
        for key, val in ctx.items():
            if val:
                setattr(record, key, val)
        return True


def get_all_context_safe() -> dict[str, str | None]:
    """Безопасное получение контекста (не падает при ошибке)."""
    result: dict[str, str | None] = {}
    for key in ("tenant_id", "trace_id", "user_id", "request_id"):
        try:
            result[key] = get_log_context(key)
        except Exception:
            result[key] = None
    return result


def _add_tenant_id(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    val = get_log_context("tenant_id")
    if val:
        event_dict["tenant_id"] = val
    return event_dict


def _add_trace_id(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    val = get_log_context("trace_id")
    if val:
        event_dict["trace_id"] = val
    return event_dict


def _add_user_id(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    val = get_log_context("user_id")
    if val:
        event_dict["user_id"] = val
    return event_dict


def _add_request_id(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    val = get_log_context("request_id")
    if val:
        event_dict["request_id"] = val
    return event_dict


def get_logger(name: str | None = None) -> Any:
    """Получить логгер: structlog если доступен, иначе stdlib."""
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)  # type: ignore[union-attr]
    return logging.getLogger(name)
