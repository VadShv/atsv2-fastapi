"""Домен вакансий.

Агрегат Vacancy — центральный для рекрутинга. Хранит описание роли,
из которого AI генерирует критерии скрининга.

JUGO-120: канонический description, статусы draft/open/on_hold/closed/canceled,
команда найма, CRUD, события.
JUGO-124: статусная машина (валидные переходы, права, события published/closed),
счётчик hired_count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import ProvenanceId, TenantId, VacancyId


class VacancyStatus(StrEnum):
    """Статусы вакансии (ТЗ §8.1)."""

    DRAFT = "draft"
    OPEN = "open"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    CANCELED = "canceled"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    LEAD = "lead"
    HEAD = "head"


# JUGO-124: Допустимые переходы статусной машины вакансии.
# Терминальные статусы не имеют переходов (кроме closed→open для повторного открытия).
VACANCY_TRANSITIONS: dict[VacancyStatus, set[VacancyStatus]] = {
    VacancyStatus.DRAFT: {VacancyStatus.OPEN, VacancyStatus.CANCELED},
    VacancyStatus.OPEN: {VacancyStatus.ON_HOLD, VacancyStatus.CLOSED, VacancyStatus.CANCELED},
    VacancyStatus.ON_HOLD: {VacancyStatus.OPEN, VacancyStatus.CLOSED, VacancyStatus.CANCELED},
    VacancyStatus.CLOSED: {VacancyStatus.OPEN},  # повторное открытие
    VacancyStatus.CANCELED: set(),  # терминальная
}

TERMINAL_VACANCY_STATUSES = frozenset({VacancyStatus.CLOSED, VacancyStatus.CANCELED})


class InvalidVacancyTransitionError(Exception):
    """Недопустимый переход статуса вакансии."""


@dataclass(frozen=True)
class RoleDescription:
    """Структурированное описание роли — вход для AI-генерации критериев."""

    title: str
    seniority: Seniority
    team: str
    description: str  # свободный текст: обязанности, требования, условия
    requirements: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)


# --- Доменные события ---


@dataclass(frozen=True)
class VacancyCreated(DomainEvent):
    vacancy_id: UUID = field(default_factory=uuid4)
    title: str = ""
    seniority: str = ""
    team: str = ""
    status: str = "draft"


@dataclass(frozen=True)
class ScreeningCriteriaGenerated(DomainEvent):
    vacancy_id: UUID = field(default_factory=uuid4)
    provenance_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class VacancyPublished(DomainEvent):
    """Событие: вакансия опубликована (draft → open)."""

    vacancy_id: UUID = field(default_factory=uuid4)
    title: str = ""
    team: str = ""


@dataclass(frozen=True)
class VacancyClosed(DomainEvent):
    """Событие: вакансия закрыта."""

    vacancy_id: UUID = field(default_factory=uuid4)
    hired_count: int = 0


@dataclass(frozen=True)
class VacancyStatusChanged(DomainEvent):
    """Событие: статус вакансии изменён."""

    vacancy_id: UUID = field(default_factory=uuid4)
    from_status: str = ""
    to_status: str = ""


@dataclass
class Vacancy(AggregateRoot):
    """Агрегат Vacancy. Мутабельный — меняет статус и привязывает критерии.

    Инварианты:
    - Статус DRAFT → OPEN требует заполненного описания роли.
    - Переходы только по VACANCY_TRANSITIONS.
    - Критерии скрининга привязаны к вакансии через provenance (whitebox).
    - hired_count обновляется при найме кандидата на вакансию.
    """

    # non-default поля — первыми
    id: VacancyId
    tenant_id: TenantId
    role: RoleDescription
    # default поля — после
    status: VacancyStatus = VacancyStatus.DRAFT
    hiring_team: str = ""  # JUGO-120: команда найма
    screening_criteria_provenance: ProvenanceId | None = None
    hired_count: int = 0  # JUGO-124: счётчик нанятых
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = None  # JUGO-124: дата закрытия
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        role: RoleDescription,
        hiring_team: str = "",
    ) -> Vacancy:
        """Фабрика создания вакансии. Публикует VacancyCreated."""
        vacancy = cls(
            id=VacancyId.generate(),
            tenant_id=tenant_id,
            role=role,
            hiring_team=hiring_team or role.team,
        )
        vacancy._record(
            VacancyCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={"title": role.title, "seniority": role.seniority.value},
                vacancy_id=vacancy.id.value,
                title=role.title,
                seniority=role.seniority.value,
                team=role.team,
                status=vacancy.status.value,
            )
        )
        return vacancy

    def attach_screening_criteria(self, provenance_id: ProvenanceId) -> None:
        """Привязать сгенерированные критерии скрининга (по provenance)."""
        self.screening_criteria_provenance = provenance_id
        self.updated_at = datetime.now(UTC)
        self._record(
            ScreeningCriteriaGenerated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={"vacancy_id": str(self.id.value)},
                vacancy_id=self.id.value,
                provenance_id=provenance_id.value,
            )
        )

    def _transition_to(self, target: VacancyStatus) -> None:
        """Внутренний метод перехода статуса с проверкой."""
        if target == self.status:
            return  # идемпотентность

        allowed = VACANCY_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            raise InvalidVacancyTransitionError(
                f"Переход {self.status.value} → {target.value} недопустим"
            )

        from_status = self.status
        self.status = target
        self.updated_at = datetime.now(UTC)

        if target in TERMINAL_VACANCY_STATUSES:
            self.closed_at = datetime.now(UTC)

        self._record(
            VacancyStatusChanged(
                event_id=uuid4(),
                occurred_at=self.updated_at,
                tenant_id=self.tenant_id.value,
                payload={"from_status": from_status.value, "to_status": target.value},
                vacancy_id=self.id.value,
                from_status=from_status.value,
                to_status=target.value,
            )
        )

    def publish(self) -> None:
        """Опубликовать вакансию: DRAFT → OPEN.

        Требует заполненное описание роли.
        Публикует событие VacancyPublished.
        """
        if not self.role.description.strip():
            raise ValueError("Cannot publish vacancy without role description")
        self._transition_to(VacancyStatus.OPEN)
        self._record(
            VacancyPublished(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={"title": self.role.title},
                vacancy_id=self.id.value,
                title=self.role.title,
                team=self.hiring_team,
            )
        )

    def put_on_hold(self) -> None:
        """Заморозить вакансию: OPEN → ON_HOLD."""
        self._transition_to(VacancyStatus.ON_HOLD)

    def resume_publishing(self) -> None:
        """Возобновить: ON_HOLD/CLOSED → OPEN."""
        self._transition_to(VacancyStatus.OPEN)

    def close(self) -> None:
        """Закрыть вакансию: OPEN/ON_HOLD → CLOSED.

        Публикует событие VacancyClosed с hired_count.
        """
        self._transition_to(VacancyStatus.CLOSED)
        self._record(
            VacancyClosed(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={"hired_count": self.hired_count},
                vacancy_id=self.id.value,
                hired_count=self.hired_count,
            )
        )

    def cancel(self) -> None:
        """Отменить вакансию: DRAFT/OPEN/ON_HOLD → CANCELED (терминальная)."""
        self._transition_to(VacancyStatus.CANCELED)

    def increment_hired(self) -> None:
        """Увеличить счётчик нанятых (вызывается при HIRED в Application)."""
        self.hired_count += 1
        self.updated_at = datetime.now(UTC)

    @property
    def is_terminal(self) -> bool:
        """Вакансия в терминальном статусе (closed/canceled)."""
        return self.status in TERMINAL_VACANCY_STATUSES

    @property
    def is_active(self) -> bool:
        """Вакансия активна (открыта для приёма заявок)."""
        return self.status == VacancyStatus.OPEN

    def update_role(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
        requirements: list[str] | None = None,
        nice_to_have: list[str] | None = None,
        team: str | None = None,
        hiring_team: str | None = None,
    ) -> None:
        """Обновить поля описания роли (patch-семантика).

        Нельзя менять роль в терминальном статусе.
        """
        if self.is_terminal:
            raise ValueError("Cannot update role of a closed/canceled vacancy")

        new_title = title.strip() if title is not None and title.strip() else self.role.title
        new_description = description if description is not None else self.role.description
        new_requirements = requirements if requirements is not None else self.role.requirements
        new_nice_to_have = nice_to_have if nice_to_have is not None else self.role.nice_to_have
        new_team = team if team is not None and team.strip() else self.role.team

        self.role = RoleDescription(
            title=new_title,
            seniority=self.role.seniority,
            team=new_team,
            description=new_description,
            requirements=new_requirements,
            nice_to_have=new_nice_to_have,
        )

        if hiring_team is not None and hiring_team.strip():
            self.hiring_team = hiring_team.strip()

        self.updated_at = datetime.now(UTC)

    def to_payload(self) -> dict[str, str]:
        return {
            "vacancy_id": str(self.id.value),
            "title": self.role.title,
        }
