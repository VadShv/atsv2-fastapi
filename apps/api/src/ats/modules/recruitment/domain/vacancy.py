"""Домен вакансий.

Агрегат Vacancy — центральный для рекрутинга. Хранит описание роли,
из которого AI генерирует критерии скрининга.
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
    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSED = "closed"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    LEAD = "lead"
    HEAD = "head"


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


@dataclass
class Vacancy(AggregateRoot):
    """Агрегат Vacancy. Мутабельный — меняет статус и привязывает критерии.

    Инварианты:
    - Статус DRAFT → ACTIVE требует заполненного описания роли.
    - Критерии скрининга привязаны к вакансии через provenance (whitebox).
    """

    # non-default поля — первыми
    id: VacancyId
    tenant_id: TenantId
    role: RoleDescription
    # default поля — после
    status: VacancyStatus = VacancyStatus.DRAFT
    screening_criteria_provenance: ProvenanceId | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(cls, tenant_id: TenantId, role: RoleDescription) -> Vacancy:
        """Фабрика создания вакансии. Публикует VacancyCreated."""
        vacancy = cls(
            id=VacancyId.generate(),
            tenant_id=tenant_id,
            role=role,
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

    def activate(self) -> None:
        if not self.role.description.strip():
            raise ValueError("Cannot activate vacancy without role description")
        self.status = VacancyStatus.ACTIVE
        self.updated_at = datetime.now(UTC)

    def to_payload(self) -> dict[str, str]:
        return {
            "vacancy_id": str(self.id.value),
            "title": self.role.title,
        }
