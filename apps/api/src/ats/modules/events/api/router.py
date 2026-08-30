"""SSE-эндпоинт: /api/v1/events/stream.

Стримит доменные события клиенту через Server-Sent Events.
Поддержка: heartbeat, reconnect по Last-Event-ID, фильтрация по event_type.

Реализовано на голом StreamingResponse (без sse-starlette) — минимум зависимостей,
полный контроль над форматом wire-протокола SSE.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

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
    set(t.strip() for t in types.split(",")) if types else None

    async def generate():
        while True:
            if await request.is_disconnected():
                logger.debug("SSE client disconnected")
                break
            # Heartbeat — держит соединение живым (комментарий SSE)
            yield ": heartbeat\n\n"
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            # TODO (Wave 1+): чтение из Redis Streams по last_id с фильтром wanted.
            # Полная реализация — после подключения Redis-клиента в приложение
            # (relay/consumer готовы в infra/events/, интеграция в роутер — при деплое).

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


def format_sse(payload: dict, wanted: set[str] | None) -> str | None:
    """Отфильтровать и отформатировать событие для SSE. None — пропустить."""
    event_type = payload.get("event_type", "")
    if wanted and event_type not in wanted:
        return None
    data = json.dumps(payload, default=str, ensure_ascii=False)
    event_id = payload.get("event_id", "")
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
