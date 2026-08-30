"""Структурное логирование (JUGO-032).

JSON-логи с tenant_id/trace_id + маскирование ПД.
- setup_logging() — инициализация structlog (вызывается в main.py/cli.py)
- RequestContextMiddleware — прокидывает request_id/trace_id
- context — contextvars для tenant_id/trace_id/user_id
- pii_mask — маскирование email/телефона/ФИО
"""

from ats.infra.logging.context import (
    clear_context,
    get_all_context,
    get_log_context,
    set_context,
    set_log_context,
)
from ats.infra.logging.middleware import RequestContextMiddleware
from ats.infra.logging.pii_mask import mask_pii_processor
from ats.infra.logging.settings import settings as log_settings
from ats.infra.logging.setup import get_logger, setup_logging

__all__ = [
    "RequestContextMiddleware",
    "clear_context",
    "get_all_context",
    "get_log_context",
    "get_logger",
    "log_settings",
    "mask_pii_processor",
    "set_context",
    "set_log_context",
    "setup_logging",
]
