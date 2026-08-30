"""Тесты инфраструктуры событий: in-process bus, envelope, relay, consumer, SSE."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ats.infra.events.bus import InProcessEventBus
from ats.infra.events.consumer import ConsumerConfig, EventConsumer
from ats.infra.events.relay import OutboxRelay, topic_for
from ats.shared.events import ActorRef, DomainEvent, EventEnvelope

# ---------------------------------------------------------------------------
# EventEnvelope
# ---------------------------------------------------------------------------


def _make_event(payload=None):
    return DomainEvent(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        tenant_id=uuid4(),
        payload=payload or {},
    )


def test_envelope_to_dict_has_required_fields():
    """Конверт строится по зарегистрированному типу и содержит все поля контракта."""
    # VacancyCreated зарегистрирован — используем его для проверки структуры
    from ats.modules.recruitment.domain.vacancy import Seniority, VacancyCreated, VacancyStatus

    ev = VacancyCreated(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        title="Backend",
        seniority=Seniority.SENIOR.value,
        team="Platform",
        status=VacancyStatus.DRAFT.value,
    )
    envelope = EventEnvelope.from_event(ev, actor=ActorRef.user("user-1"))
    d = envelope.to_dict()
    assert d["event_type"] == "vacancy.created"
    assert d["schema_version"] == 1
    assert d["actor"] == {"type": "user", "id": "user-1"}
    assert d["aggregate"]["type"] == "vacancy"
    assert d["tenant_id"] == str(ev.tenant_id)
    assert "payload" in d
    assert "occurred_at" in d
    assert "event_id" in d


def test_envelope_actor_defaults_to_system():
    from ats.modules.recruitment.domain.vacancy import Seniority, VacancyCreated, VacancyStatus

    ev = VacancyCreated(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        title="X",
        seniority=Seniority.JUNIOR.value,
        team="T",
        status=VacancyStatus.DRAFT.value,
    )
    envelope = EventEnvelope.from_event(ev)
    assert envelope.actor.type.value == "system"
    assert envelope.actor.id is None


def test_actor_ref_factories():
    assert ActorRef.user("u").type.value == "user"
    assert ActorRef.system().id is None
    assert ActorRef.ai_agent("a").type.value == "ai_agent"
    assert ActorRef.integration("i").type.value == "integration"


# ---------------------------------------------------------------------------
# InProcessEventBus
# ---------------------------------------------------------------------------


def test_in_process_bus_delivers_to_subscribers():
    bus = InProcessEventBus()
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe("DomainEvent", handler)
    event = _make_event()
    bus.publish(event)
    assert received == [event]


def test_in_process_bus_handler_failure_does_not_block_others():
    bus = InProcessEventBus()
    results = []

    def bad_handler(_event):
        raise RuntimeError("boom")

    def good_handler(_event):
        results.append("ok")

    bus.subscribe("DomainEvent", bad_handler)
    bus.subscribe("DomainEvent", good_handler)
    bus.publish(_make_event())
    assert results == ["ok"]


def test_in_process_bus_no_subscribers_is_noop():
    bus = InProcessEventBus()
    bus.publish(_make_event())  # не падает


# ---------------------------------------------------------------------------
# Relay: topic routing
# ---------------------------------------------------------------------------


def test_topic_for_core_event():
    assert topic_for("vacancy.created") == "events:core"
    assert topic_for("application.stage.changed") == "events:core"


def test_topic_for_ai_event():
    assert topic_for("ai.run.completed") == "events:ai"
    assert topic_for("ai.screening.scored") == "events:ai"


@pytest.mark.asyncio
async def test_relay_construction_defaults():
    """Relay строится с дефолтами; полный цикл с БД — в интеграционных тестах."""
    relay = OutboxRelay(
        session_factory=None,  # type: ignore[arg-type]
        redis_client=None,
        batch_size=10,
    )
    assert relay._batch_size == 10
    assert relay._max_attempts == 5
    assert relay._poll_interval == 1.0


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_processes_message_without_redis():
    """Consumer без Redis: хендлер вызывается, ack/seen — no-op."""
    config = ConsumerConfig(stream="events:core", group="g1", consumer_name="c1")
    consumer = EventConsumer(config, redis_client=None)

    called = []

    async def handler(payload):
        called.append(payload["event_type"])

    consumer.subscribe("vacancy.created", handler)

    payload = {"event_id": "e1", "event_type": "vacancy.created", "data": {}}
    stats = await consumer.process_message("msg-1", {"data": json.dumps(payload)})

    assert called == ["vacancy.created"]
    assert stats.processed == 1
    assert stats.failed == 0


@pytest.mark.asyncio
async def test_consumer_retries_then_dlq():
    """Хендлер падает N раз → после max_retries → DLQ."""
    config = ConsumerConfig(
        stream="events:core",
        group="g1",
        consumer_name="c1",
        max_retries=2,
        retry_base_delay=0.0,
    )
    consumer = EventConsumer(config, redis_client=None)

    attempts = []

    async def bad_handler(_payload):
        attempts.append(1)
        raise RuntimeError("always fails")

    consumer.subscribe("vacancy.created", bad_handler)
    payload = {"event_id": "e2", "event_type": "vacancy.created"}
    stats = await consumer.process_message("msg-2", {"data": json.dumps(payload)})

    assert len(attempts) == config.max_retries
    assert stats.failed == 1
    assert stats.dlq == 1


@pytest.mark.asyncio
async def test_consumer_no_handlers_acks_message():
    """Событие без подписчиков — ack без обработки."""
    config = ConsumerConfig(stream="events:core", group="g1", consumer_name="c1")
    consumer = EventConsumer(config, redis_client=None)
    payload = {"event_id": "e3", "event_type": "unknown.event"}
    stats = await consumer.process_message("msg-3", {"data": json.dumps(payload)})
    assert stats.processed == 0
    assert stats.failed == 0


# ---------------------------------------------------------------------------
# Fake Redis для проверки дедупликации
# ---------------------------------------------------------------------------


class FakeRedis:
    """Минимальный фейк Redis для тестов consumer."""

    def __init__(self):
        self.sets: dict[str, set[str]] = {}
        self.streams: dict[str, list] = {}
        self.acks: list = []

    async def sismember(self, key, val):
        return val in self.sets.get(key, set())

    async def sadd(self, key, val):
        self.sets.setdefault(key, set()).add(val)

    async def xack(self, stream, group, msg_id):
        self.acks.append(msg_id)

    async def xadd(self, stream, fields):
        self.streams.setdefault(stream, []).append(fields)


@pytest.mark.asyncio
async def test_consumer_deduplication_with_redis():
    config = ConsumerConfig(stream="events:core", group="g1", consumer_name="c1")
    fake = FakeRedis()
    consumer = EventConsumer(config, redis_client=fake)

    calls = []

    async def handler(payload):
        calls.append(payload["event_id"])

    consumer.subscribe("vacancy.created", handler)
    payload = {"event_id": "dup-1", "event_type": "vacancy.created"}

    # Первая обработка
    await consumer.process_message("m1", {"data": json.dumps(payload)})
    # Вторая (дубликат)
    stats = await consumer.process_message("m2", {"data": json.dumps(payload)})

    assert len(calls) == 1
    assert stats.deduplicated == 1


# ---------------------------------------------------------------------------
# InProcessEventBus: SSE-очереди
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_subscribe_queue_receives_envelope():
    """Публикация в шину → конверт попадает в SSE-очередь."""
    bus = InProcessEventBus()
    queue = bus.subscribe_queue()

    from ats.modules.recruitment.domain.vacancy import Seniority, VacancyCreated, VacancyStatus

    event = VacancyCreated(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        title="Backend",
        seniority=Seniority.SENIOR.value,
        team="Platform",
        status=VacancyStatus.DRAFT.value,
    )
    bus.publish(event)

    envelope = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert envelope["event_type"] == "vacancy.created"
    assert envelope["event_id"] == str(event.event_id)
    assert envelope["aggregate"]["type"] == "vacancy"
    assert "payload" in envelope
    bus.unsubscribe_queue(queue)


@pytest.mark.asyncio
async def test_bus_unsubscribe_queue_stops_delivery():
    """После unsubscribe очередь больше не получает события."""
    bus = InProcessEventBus()
    queue = bus.subscribe_queue()
    bus.unsubscribe_queue(queue)

    from ats.modules.recruitment.domain.vacancy import Seniority, VacancyCreated, VacancyStatus

    event = VacancyCreated(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        title="X",
        seniority=Seniority.JUNIOR.value,
        team="T",
        status=VacancyStatus.DRAFT.value,
    )
    bus.publish(event)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_bus_publish_envelope_delivers_to_queue():
    """publish_envelope кладёт готовый конверт в SSE-очередь."""
    bus = InProcessEventBus()
    queue = bus.subscribe_queue()
    envelope_dict = {"event_id": "x1", "event_type": "vacancy.created", "payload": {}}
    bus.publish_envelope(envelope_dict)
    result = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert result == envelope_dict
    bus.unsubscribe_queue(queue)


def test_format_sse_filters_and_formats():
    """format_sse: фильтрует по wanted и форматирует SSE-строку."""
    from ats.modules.events.api.router import format_sse

    payload = {"event_id": "e1", "event_type": "vacancy.created", "payload": {"x": 1}}

    # Без фильтра — проходит
    out = format_sse(payload, None)
    assert out is not None
    assert "id: e1" in out
    assert "event: vacancy.created" in out
    assert "data: " in out

    # С фильтром — проходит
    out2 = format_sse(payload, {"vacancy.created"})
    assert out2 is not None

    # С фильтром — не проходит
    out3 = format_sse(payload, {"candidate.created"})
    assert out3 is None


# ---------------------------------------------------------------------------
# Consumer: replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_replay_without_redis_returns_empty():
    """Replay без Redis — no-op, возвращает пустые stats."""
    config = ConsumerConfig(stream="events:core", group="g1", consumer_name="c1")
    consumer = EventConsumer(config, redis_client=None)
    stats = await consumer.replay()
    assert stats.processed == 0
    assert stats.failed == 0


class FakeStreamRedis(FakeRedis):
    """Фейк Redis с поддержкой xrange для replay."""

    def __init__(self):
        super().__init__()
        self.xrange_data: dict[str, list[tuple[str, dict]]] = {}

    async def xrange(self, stream, min="0", count=1000):
        return self.xrange_data.get(stream, [])


@pytest.mark.asyncio
async def test_consumer_replay_processes_messages():
    """Replay читает xrange и прогоняет через хендлеры."""
    config = ConsumerConfig(stream="events:core", group="g1", consumer_name="c1")
    fake = FakeStreamRedis()
    fake.xrange_data = {
        "events:core": [
            ("1-0", {"data": json.dumps({"event_id": "r1", "event_type": "vacancy.created"})}),
            ("2-0", {"data": json.dumps({"event_id": "r2", "event_type": "candidate.created"})}),
        ]
    }
    consumer = EventConsumer(config, redis_client=fake)

    seen = []

    async def handler(payload):
        seen.append(payload["event_id"])

    consumer.subscribe("vacancy.created", handler)
    consumer.subscribe("candidate.created", handler)

    stats = await consumer.replay()
    assert stats.processed == 2
    assert set(seen) == {"r1", "r2"}


@pytest.mark.asyncio
async def test_consumer_replay_filters_by_event_types():
    """Replay с event_types фильтрует сообщения."""
    config = ConsumerConfig(stream="events:core", group="g1", consumer_name="c1")
    fake = FakeStreamRedis()
    fake.xrange_data = {
        "events:core": [
            ("1-0", {"data": json.dumps({"event_id": "r1", "event_type": "vacancy.created"})}),
            ("2-0", {"data": json.dumps({"event_id": "r2", "event_type": "candidate.created"})}),
        ]
    }
    consumer = EventConsumer(config, redis_client=fake)

    seen = []

    async def handler(payload):
        seen.append(payload["event_id"])

    consumer.subscribe("vacancy.created", handler)
    consumer.subscribe("candidate.created", handler)

    stats = await consumer.replay(event_types=["vacancy.created"])
    assert stats.processed == 1
    assert seen == ["r1"]


# ---------------------------------------------------------------------------
# SSE эндпоинт: проверка регистрации маршрута и форматирования
# ---------------------------------------------------------------------------


def test_sse_endpoint_registered():
    """Маршрут /api/v1/events/stream зарегистрирован в приложении."""
    from ats.infra.container_helpers import reset_container
    from ats.main import app

    reset_container()
    # Проверяем, что маршрут доступен через url_path_for / openapi
    openapi = app.openapi()
    assert "/api/v1/events/stream" in openapi["paths"]
    reset_container()
