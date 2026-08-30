"""Доменные события и событийный конверт v1.

Модули общаются только через события (in-process bus).
События пишутся в outbox в той же транзакции, что и агрегат (устойчивость).

Контракт конверта — ТЗ §4.3, зафиксирован в contracts/events/envelope.schema.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Типизированные доменные события (in-process)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainEvent:
    """Базовый доменный event. Имена подклассов — PastTense (напр. VacancyCreated)."""

    event_id: UUID
    occurred_at: datetime
    tenant_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(cls, tenant_id: UUID, payload: dict[str, Any] | None = None) -> DomainEvent:
        return cls(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            tenant_id=tenant_id,
            payload=payload or {},
        )


# ---------------------------------------------------------------------------
# Конверт события v1 (контракт §4.3 ТЗ)
# ---------------------------------------------------------------------------


class ActorType(StrEnum):
    """Кто инициировал изменение."""

    USER = "user"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"
    INTEGRATION = "integration"


@dataclass(frozen=True)
class ActorRef:
    """Ссылка на субъекта изменения."""

    type: ActorType
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "id": self.id}

    @classmethod
    def user(cls, user_id: str) -> ActorRef:
        return cls(type=ActorType.USER, id=user_id)

    @classmethod
    def system(cls) -> ActorRef:
        return cls(type=ActorType.SYSTEM)

    @classmethod
    def ai_agent(cls, agent_id: str) -> ActorRef:
        return cls(type=ActorType.AI_AGENT, id=agent_id)

    @classmethod
    def integration(cls, integration_id: str) -> ActorRef:
        return cls(type=ActorType.INTEGRATION, id=integration_id)


@dataclass(frozen=True)
class AggregateRef:
    """Ссылка на агрегат — носитель события."""

    type: str
    id: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id}


# Реестр: имя доменного класса событий → (event_type, schema_version, aggregate_type)
# event_type — dot.notation без underscores (конвенция контракта §4.3).
_EVENT_TYPE_REGISTRY: dict[str, tuple[str, int, str]] = {
    "VacancyCreated": ("vacancy.created", 1, "vacancy"),
    "ScreeningCriteriaGenerated": ("vacancy.screening.generated", 1, "vacancy"),
    "CandidateCreated": ("candidate.created", 1, "candidate"),
    "CandidateUpdated": ("candidate.updated", 1, "candidate"),
    "ResumeAttached": ("candidate.resume.attached", 1, "candidate"),
    "ApplicationCreated": ("application.created", 1, "application"),
    "StageChanged": ("application.stage.changed", 1, "application"),
}


def _resolve_event_type(event: DomainEvent) -> tuple[str, int, str]:
    """Сопоставить доменный event с его контрактом (event_type, version, aggregate)."""
    cls_name = type(event).__name__
    try:
        return _EVENT_TYPE_REGISTRY[cls_name]
    except KeyError as exc:  # pragma: no cover - защитная проверка
        raise ValueError(
            f"Доменное событие {cls_name!r} не зарегистрировано в контракте. "
            "Добавьте запись в _EVENT_TYPE_REGISTRY и JSON Schema в contracts/events/."
        ) from exc


@dataclass(frozen=True)
class EventEnvelope:
    """Единый конверт события для outbox и Redis Streams (контракт §4.3).

    Сериализуется в JSON для записи в outbox.events_payload и публикации в стрим.
    Доменные dataclass-события остаются типизированными в коде; конверт —
    транспортный формат на границе модулей.
    """

    event_id: UUID
    event_type: str
    schema_version: int
    occurred_at: datetime
    tenant_id: UUID
    actor: ActorRef
    aggregate: AggregateRef
    payload: dict[str, Any]

    @classmethod
    def from_event(
        cls,
        event: DomainEvent,
        actor: ActorRef | None = None,
        aggregate_id: str | None = None,
    ) -> EventEnvelope:
        """Упаковать типизированное доменное событие в конверт контракта.

        Args:
            event: доменное событие (dataclass).
            actor: кто инициировал. По умолчанию system.
            aggregate_id: идентификатор агрегата. Если None — берётся из payload
                или собственных полей события по ключу агрегата.
        """
        event_type, schema_version, aggregate_type = _resolve_event_type(event)
        ref_actor = actor or ActorRef(type=ActorType.SYSTEM)

        if aggregate_id is None:
            aggregate_id = _extract_aggregate_id(event, aggregate_type)

        return cls(
            event_id=event.event_id,
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=event.occurred_at,
            tenant_id=event.tenant_id,
            actor=ref_actor,
            aggregate=AggregateRef(type=aggregate_type, id=aggregate_id),
            payload=_resolve_payload(event),
        )

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для outbox (jsonb) и Redis Streams."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "tenant_id": str(self.tenant_id),
            "actor": self.actor.to_dict(),
            "aggregate": self.aggregate.to_dict(),
            "payload": self.payload,
        }


# Поля dataclass-событий, которые переносятся в payload конверта (если есть).
_PAYLOAD_FIELDS = (
    "vacancy_id",
    "provenance_id",
    "candidate_id",
    "application_id",
    "from_stage",
    "to_stage",
    "from_stage_id",
    "to_stage_id",
    "stage",
    "source",
    "status",
    "resume_provenance_id",
    "full_name",
    "fields_changed",
    "title",
    "seniority",
    "team",
    "reason",
)


def _extract_aggregate_id(event: DomainEvent, aggregate_type: str) -> str:
    """Достать id агрегата из payload или собственных полей события."""
    key = f"{aggregate_type}_id"
    if key in event.payload:
        return str(event.payload[key])
    val = getattr(event, key, None)
    if val is not None:
        return str(val)
    # Для StageChanged/application — application_id
    alt = getattr(event, "application_id", None)
    if alt is not None:
        return str(alt)
    raise ValueError(
        f"Не удалось определить id агрегата {aggregate_type!r} для события {type(event).__name__}"
    )


def _resolve_payload(event: DomainEvent) -> dict[str, Any]:
    """Собрать payload конверта: payload события + типизированные поля."""
    payload = dict(event.payload)
    for attr in _PAYLOAD_FIELDS:
        val = getattr(event, attr, None)
        if val is not None and attr not in payload:
            payload[attr] = str(val) if isinstance(val, UUID) else val
    return payload


# ---------------------------------------------------------------------------
# Порт шины событий
# ---------------------------------------------------------------------------


class EventBus(Protocol):
    """Порт: шина событий. Реализация — in-process + outbox-диспетчер."""

    def publish(self, event: DomainEvent) -> None:
        """Синхронная публикация в in-process шину (для немедленных реакций)."""
        ...

    async def enqueue_outbox(self, event: DomainEvent) -> None:
        """Запись в outbox для надёжной асинхронной доставки (at-least-once)."""
        ...
