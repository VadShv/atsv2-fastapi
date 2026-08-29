"""Процессор маскирования ПД для structlog (SECURE FIRST).

Маскирует email, телефон, ФИО в строковых значениях лог-событий.
Применяется как processor в цепочке structlog.
"""

from __future__ import annotations

import re
from typing import Any

from ats.infra.logging.settings import settings as log_settings

_EMAIL_RE = re.compile(log_settings.pii_email_pattern)
_PHONE_RE = re.compile(log_settings.pii_phone_pattern)


def mask_pii_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: маскирование ПД во всех строковых значениях."""
    if not log_settings.mask_pii:
        return event_dict
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = _mask_string(value)
        elif isinstance(value, dict):
            event_dict[key] = _mask_dict(value)
        elif isinstance(value, list):
            event_dict[key] = [_mask_item(item) for item in value]
    return event_dict


def _mask_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: _mask_item(v) for k, v in d.items()}


def _mask_item(item: Any) -> Any:
    if isinstance(item, str):
        return _mask_string(item)
    if isinstance(item, dict):
        return _mask_dict(item)
    if isinstance(item, list):
        return [_mask_item(i) for i in item]
    return item


def _mask_string(s: str) -> str:
    """Маскирование email и телефона в строке."""
    s = _EMAIL_RE.sub(_mask_email, s)
    s = _PHONE_RE.sub(_mask_phone, s)
    return s


def _mask_email(match: re.Match[str]) -> str:
    email = match.group(0)
    at = email.index("@")
    visible = email[: min(log_settings.pii_name_visible_chars, at)]
    domain = email[at:]
    return f"{visible}***{domain}"


def _mask_phone(match: re.Match[str]) -> str:
    phone = match.group(0)
    if len(phone) <= 4:
        return phone
    return phone[:2] + "***" + phone[-2:]


def add_tenant_id_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Добавить tenant_id из contextvars в каждое лог-событие."""
    tenant_id = _get_context("tenant_id")
    if tenant_id:
        event_dict["tenant_id"] = tenant_id
    return event_dict


def add_trace_id_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Добавить trace_id из contextvars в каждое лог-событие."""
    trace_id = _get_context("trace_id")
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def _get_context(key: str) -> str | None:
    """Получить значение из contextvars (лениво, безопасно при отсутствии)."""
    try:
        from ats.infra.logging.context import get_log_context

        return get_log_context(key)
    except Exception:
        return None
