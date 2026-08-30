"""Домен: версионируемые наборы критериев вакансии (JUGO-121).

RequirementSet — версия критериев скрининга для вакансии.
- Версии неизменяемы (immutable): правка → новая версия.
- origin: ai / manual / ai_edited (как получены критерии).
- Только одна активная версия на вакансию в данный момент.
- Схема criteria соответствует ТЗ §8.2 (ScreeningCriteriaOutput).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import TenantId, VacancyId


class RequirementOrigin(StrEnum):
    """Происхождение критериев (whitebox AI)."""

    AI = "ai"  # сгенерированы ИИ без правок
    MANUAL = "manual"  # созданы вручную рекрутером
    AI_EDITED = "ai_edited"  # ИИ-черновик, отредактированный рекрутером


class RequirementSetStatus(StrEnum):
    """Статус версии критериев."""

    DRAFT = "draft"  # черновик (можно редактировать)
    ACTIVE = "active"  # активная версия (используется для скрининга)
    ARCHIVED = "archived"  # архивная (заменена новой активной)


@dataclass(frozen=True)
class RequirementSetActivated(DomainEvent):
    """Событие: активирована версия критериев вакансии."""

    vacancy_id: UUID = field(default_factory=uuid4)
    requirement_set_id: UUID = field(default_factory=uuid4)
    version_number: int = 0
    origin: str = ""


@dataclass
class RequirementSet(AggregateRoot):
    """Версия набора критериев скрининга для вакансии.

    Инварианты:
    - Принадлежит конкретной вакансии (vacancy_id).
    - version_number монотонно возрастает (1, 2, 3...).
    - Критерии хранятся как JSONB (схема ScreeningCriteriaOutput из ТЗ §8.2).
    - origin указывает происхождение (whitebox).
    - provenance_id — ссылка на AI-вызов, если origin=ai/ai_edited.
    - Активной может быть только одна версия на вакансию.
    """

    id: UUID
    tenant_id: TenantId
    vacancy_id: VacancyId
    version_number: int
    criteria: dict  # JSONB: ScreeningCriteriaOutput
    origin: RequirementOrigin = RequirementOrigin.AI
    status: RequirementSetStatus = RequirementSetStatus.DRAFT
    provenance_id: UUID | None = None  # whitebox: ссылка на AI-вызов
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        vacancy_id: VacancyId,
        version_number: int,
        criteria: dict,
        origin: RequirementOrigin = RequirementOrigin.AI,
        provenance_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> RequirementSet:
        """Создать новую версию критериев (статус = DRAFT)."""
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            vacancy_id=vacancy_id,
            version_number=version_number,
            criteria=criteria,
            origin=origin,
            status=RequirementSetStatus.DRAFT,
            provenance_id=provenance_id,
            created_by=created_by,
        )

    def activate(self) -> None:
        """Активировать версию критериев.

        Публикует событие RequirementSetActivated.
        Менеджер репозитория должен архивировать предыдущую активную версию.
        """
        self.status = RequirementSetStatus.ACTIVE
        self.activated_at = datetime.now(UTC)
        self._record(
            RequirementSetActivated(
                event_id=uuid4(),
                occurred_at=self.activated_at,
                tenant_id=self.tenant_id.value,
                payload={
                    "vacancy_id": str(self.vacancy_id.value),
                    "requirement_set_id": str(self.id),
                    "version_number": self.version_number,
                    "origin": self.origin.value,
                },
                vacancy_id=self.vacancy_id.value,
                requirement_set_id=self.id,
                version_number=self.version_number,
                origin=self.origin.value,
            )
        )

    def archive(self) -> None:
        """Архивировать версию (снять с активной)."""
        self.status = RequirementSetStatus.ARCHIVED

    def is_active(self) -> bool:
        return self.status == RequirementSetStatus.ACTIVE

    def to_dict(self) -> dict:
        """Сериализация для API."""
        return {
            "id": str(self.id),
            "vacancy_id": str(self.vacancy_id.value),
            "version_number": self.version_number,
            "criteria": self.criteria,
            "origin": self.origin.value,
            "status": self.status.value,
            "provenance_id": str(self.provenance_id) if self.provenance_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "activated_at": (self.activated_at.isoformat() if self.activated_at else None),
        }
