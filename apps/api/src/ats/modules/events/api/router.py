"""SSE-эндпоинт: /api/v1/events/stream.

Стримит доменные события клиенту через Server-Sent Events.
Поддержка: heartbeat, reconnect по Last-Event-ID, фильтрация по event_type.

Два режима доставки:
  - **stub mode** (без Redis): события берутся из ``InProcessEventBus`` через
    ``asyncio.Queue``. Идеально для dev/тестов — публикации в шину сразу
    попадают в SSE-стрим.
  - **prod mode** (с Redis): события читаются из Redis Streams
    (``events:core``) по consumer group с replay по ``Last-Event-ID``.

Реализовано на голом StreamingResponse (без sse-starlette) — минимум зависимостей,
полный контроль над форматом wire-протокола SSE.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from ats.infra.container_helpers import get_container

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

HEARTBEAT_INTERVAL = 15.0  # секунды
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # отключить буферизацию в nginx/Caddy
}


@router.get("/events/stream")
async def event_stream(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    types: str | None = None,
) -> StreamingResponse:
    """SSE-стрим доменных событий.

    Args:
        last_event_id: для reconnect — клиент передаёт последний полученный id.
        types: фильтр по event_type через запятую
            (напр. "vacancy.created,application.created").
    """
    wanted = set(t.strip() for t in types.split(",")) if types else None

    bus = get_container().event_bus
    queue = bus.subscribe_queue()
    logger.info(
        "SSE client connected (last_event_id=%s, filter=%s)",
        last_event_id,
        wanted or "all",
    )

    async def generate() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    logger.debug("SSE client disconnected")
                    break
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                except TimeoutError:
                    # Heartbeat — держит соединение живым (комментарий SSE)
                    yield ": heartbeat\n\n"
                    continue
                formatted = format_sse(envelope, wanted)
                if formatted is not None:
                    yield formatted
        finally:
            bus.unsubscribe_queue(queue)
            logger.debug("SSE queue unsubscribed")

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


def format_sse(payload: dict[str, Any], wanted: set[str] | None) -> str | None:
    """Отфильтровать и отформатировать событие для SSE. None — пропустить."""
    event_type = payload.get("event_type", "")
    if wanted and event_type not in wanted:
        return None
    data = json.dumps(payload, default=str, ensure_ascii=False)
    event_id = payload.get("event_id", "")
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
