"""Тесты инфраструктуры событий: in-process bus, envelope, relay, consumer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
        occurred_at=datetime.now(timezone.utc),
        tenant_id=uuid4(),
        payload=payload or {},
    )


def test_envelope_to_dict_has_required_fields():
    """Конверт строится по зарегистрированному типу и содержит все поля контракта."""
    event = _make_event({"vacancy_id": "abc", "title": "X"})
    # VacancyCreated зарегистрирован — используем его для проверки структуры
    from ats.modules.recruitment.domain.vacancy import VacancyCreated, Seniority, VacancyStatus

    ev = VacancyCreated(
        event_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
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
    from ats.modules.recruitment.domain.vacancy import VacancyCreated, Seniority, VacancyStatus

    ev = VacancyCreated(
        event_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
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
