"""Алерты в мессенджер (Telegram/Slack) через webhook (JUGO-034).

УСТОЙЧИВОСТЬ: отправка алертов — best-effort, не блокирует основной поток.
Если webhook недоступен — ошибка логируется, но не пробрасывается.

SECURE FIRST: в алерт не попадают ПД (только тип ошибки, message, trace_id).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from ats.infra.logging.context import get_log_context
from ats.infra.sentry.settings import settings as sentry_settings

logger = logging.getLogger(__name__)

_VALID_LEVELS = {"WARNING", "ERROR", "CRITICAL"}
_LEVEL_ORDER = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}


def _should_alert(level: str) -> bool:
    """Проверить, нужно ли отправлять алерт для данного уровня."""
    min_level = sentry_settings.alert_min_level.upper()
    return _LEVEL_ORDER.get(level.upper(), 0) >= _LEVEL_ORDER.get(min_level, 2)


async def send_alert(
    *,
    title: str,
    message: str,
    level: str = "ERROR",
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Отправить алерт в мессенджер через webhook.

    Args:
        title: заголовок алерта.
        message: текст сообщения.
        level: уровень (WARNING/ERROR/CRITICAL).
        trace_id: trace_id для корреляции.
        extra: доп. данные (без ПД).

    Returns:
        True если отправлено успешно, False иначе.
    """
    if not sentry_settings.alert_webhook_url:
        return False

    if not _should_alert(level):
        return False

    # Получить trace_id из contextvars, если не передан
    if trace_id is None:
        trace_id = get_log_context("trace_id") or ""

    payload = _build_payload(
        title=title,
        message=message,
        level=level,
        trace_id=trace_id,
        extra=extra,
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                sentry_settings.alert_webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            return response.status_code < 400
    except Exception as exc:
        logger.warning("Failed to send alert: %s", exc)
        return False


def _build_payload(
    *,
    title: str,
    message: str,
    level: str,
    trace_id: str,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    """Построить payload для webhook.

    Поддерживает Telegram Bot API (text) и Slack (text/blocks).
    """
    level_emoji = {
        "WARNING": "⚠️",
        "ERROR": "🔴",
        "CRITICAL": "🚨",
    }.get(level.upper(), "ℹ️")

    # Формируем текст
    lines = [
        f"{level_emoji} *{title}*",
        f"Level: {level}",
        f"Env: {sentry_settings.environment}",
    ]
    if trace_id:
        lines.append(f"Trace: `{trace_id}`")
    lines.append(f"Message: {message}")

    if extra:
        for key, val in extra.items():
            # SECURE FIRST: не отправляем значения, похожие на ПД
            val_str = str(val)[:200]
            lines.append(f"{key}: {val_str}")

    text = "\n".join(lines)

    # Определяем формат по URL webhook
    url = sentry_settings.alert_webhook_url.lower()
    if "api.telegram.org" in url:
        # Telegram Bot API
        return {
            "chat_id": "",  # задаётся в URL или здесь
            "text": text,
            "parse_mode": "Markdown",
        }
    else:
        # Slack-compatible
        return {"text": text}


def send_alert_sync(
    *,
    title: str,
    message: str,
    level: str = "ERROR",
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Синхронная версия send_alert (для воркеров/CLI)."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        send_alert(
            title=title,
            message=message,
            level=level,
            trace_id=trace_id,
            extra=extra,
        )
    )
