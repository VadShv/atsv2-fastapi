"""Context variables для логирования: tenant_id, trace_id.

Позволяют прокидывать контекст запроса через все слои без явной передачи.
Устанавливаются в middleware/воркерах, читаются в лог-процессорах.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_VARS: dict[str, ContextVar[str | None]] = {
    "tenant_id": _tenant_id,
    "trace_id": _trace_id,
    "user_id": _user_id,
    "request_id": _request_id,
}


def get_log_context(key: str) -> str | None:
    """Получить значение контекстной переменной логирования."""
    var = _VARS.get(key)
    return var.get() if var else None


def set_log_context(key: str, value: str | None) -> None:
    """Установить значение контекстной переменной логирования."""
    var = _VARS.get(key)
    if var:
        var.set(value)


def set_context(
    *,
    tenant_id: str | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Установить несколько контекстных переменных одновременно."""
    if tenant_id is not None:
        _tenant_id.set(tenant_id)
    if trace_id is not None:
        _trace_id.set(trace_id)
    if user_id is not None:
        _user_id.set(user_id)
    if request_id is not None:
        _request_id.set(request_id)


def clear_context() -> None:
    """Сбросить все контекстные переменные (при завершении запроса)."""
    for var in _VARS.values():
        var.set(None)


def get_all_context() -> dict[str, Any]:
    """Получить все контекстные переменные как dict (для метрик/audit)."""
    return {key: var.get() for key, var in _VARS.items()}
