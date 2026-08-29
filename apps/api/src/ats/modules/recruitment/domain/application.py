"""Домен заявки: Application — кандидат на вакансии с пайплайном стадий.

Центральный агрегат рекрутинга (как в Huntflow). Кандидат движется по стадиям:
Новый → Скрининг → Интервью → Оффер → Нанят / Отказ.
Переходы между стадиями — доменные события, на которые реагируют автоматизации.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import CandidateId, TenantId, VacancyId


class ApplicationStage(str, Enum):
    """Стадии пайплайна (базовый набор, как Huntflow)."""

    NEW = "new"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"


# Допустимые переходы: откуда → куда. Гарантирует консистентность воронки.
ALLOWED_TRANSITIONS: dict[ApplicationStage, set[ApplicationStage]] = {
    ApplicationStage.NEW: {
        ApplicationStage.SCREENING,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.SCREENING: {
        ApplicationStage.INTERVIEW,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.INTERVIEW: {
        ApplicationStage.OFFER,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.OFFER: {
        ApplicationStage.HIRED,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.HIRED: set(),  # терминальная
    ApplicationStage.REJECTED: {ApplicationStage.NEW},  # можно вернуть
}

# Терминальные стадии (конец воронки)
TERMINAL_STAGES = {ApplicationStage.HIRED, ApplicationStage.REJECTED}


@dataclass(frozen=True)
class ApplicationCreated(DomainEvent):
    application_id: UUID = field(default_factory=uuid4)
    candidate_id: UUID = field(default_factory=uuid4)
    vacancy_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class StageChanged(DomainEvent):
    application_id: UUID = field(default_factory=uuid4)
    from_stage: str = ""
    to_stage: str = ""
    candidate_id: UUID = field(default_factory=uuid4)
    vacancy_id: UUID = field(default_factory=uuid4)
    reason: str = ""


@dataclass
class StageTransition:
    """Запись о переходе между стадиями (история воронки)."""

    from_stage: ApplicationStage
    to_stage: ApplicationStage
    at: datetime
    reason: str = ""
    # provenance AI-оценки, если переход инициирован AI (whitebox)
    ai_provenance: UUID | None = None


@dataclass
class Application(AggregateRoot):
    """Агрегат Application: кандидат на конкретной вакансии.

    Инварианты:
    - Переход только по ALLOWED_TRANSITIONS.
    - Из терминальной стадии нельзя уйти кроме как в NEW (возврат).
    - История переходов append-only.
    """

    # non-default поля — первыми
    id: UUID
    candidate_id: CandidateId
    vacancy_id: VacancyId
    tenant_id: TenantId
    # default поля — после
    stage: ApplicationStage = ApplicationStage.NEW
    transitions: list[StageTransition] = field(default_factory=list)
    score_provenance: UUID | None = None
    score: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
    ) -> Application:
        app = cls(
            id=uuid4(),
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            tenant_id=tenant_id,
            stage=ApplicationStage.NEW,
        )
        app._record(
            ApplicationCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(timezone.utc),
                tenant_id=tenant_id.value,
                payload={
                    "candidate_id": str(candidate_id.value),
                    "vacancy_id": str(vacancy_id.value),
                },
                application_id=app.id,
                candidate_id=candidate_id.value,
                vacancy_id=vacancy_id.value,
            )
        )
        return app

    def move_to(
        self,
        to_stage: ApplicationStage,
        reason: str = "",
        ai_provenance: UUID | None = None,
    ) -> None:
        """Перевести заявку на новую стадию с проверкой перехода."""
        if to_stage == self.stage:
            return  # идемпотентность

        allowed = ALLOWED_TRANSITIONS.get(self.stage, set())
        if to_stage not in allowed:
            raise InvalidTransitionError(
                f"Переход {self.stage.value} → {to_stage.value} недопустим"
            )

        from_stage = self.stage
        self.stage = to_stage
        self.updated_at = datetime.now(timezone.utc)
        self.transitions.append(
            StageTransition(
                from_stage=from_stage,
                to_stage=to_stage,
                at=self.updated_at,
                reason=reason,
                ai_provenance=ai_provenance,
            )
        )
        self._record(
            StageChanged(
                event_id=uuid4(),
                occurred_at=self.updated_at,
                tenant_id=self.tenant_id.value,
                payload={},
                application_id=self.id,
                from_stage=from_stage.value,
                to_stage=to_stage.value,
                candidate_id=self.candidate_id.value,
                vacancy_id=self.vacancy_id.value,
                reason=reason,
            )
        )

    def set_score(self, score: float, provenance: UUID) -> None:
        """Установить AI-скоринг заявки (whitebox: ссылка на provenance)."""
        self.score = score
        self.score_provenance = provenance
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_terminal(self) -> bool:
        return self.stage in TERMINAL_STAGES


class InvalidTransitionError(Exception):
    """Недопустимый переход между стадиями пайплайна."""
