"""Домен заявки: Application — кандидат на вакансии с пайплайном стадий.

Центральный агрегат рекрутинга (как в Huntflow). Кандидат движется по стадиям:
Новый → Скрининг → Интервью → Оффер → Нанят / Отказ.
Переходы между стадиями — доменные события, на которые реагируют автоматизации.

JUGO-140: origin, current_stage_id, stage_entered_at, screening_score,
risk_level, rejection fields, CRUD + events.
JUGO-142: repeat application rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import CandidateId, TenantId, VacancyId


class ApplicationStage(StrEnum):
    """Стадии пайплайна (базовый набор, как Huntflow)."""

    NEW = "new"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"


class ApplicationOrigin(StrEnum):
    """Происхождение отклика (JUGO-140, ТЗ §1.3.2)."""

    INCOMING = "incoming"  # входящий отклик (кандидат сам подал)
    COLD_SOURCING = "cold_sourcing"  # холодный сорсинг (рекрутер нашёл)
    IMPORT = "import"  # импорт из внешнего источника
    AI_SUGGESTION = "ai_suggestion"  # ИИ-предложение (M4)


class RiskLevel(StrEnum):
    """Уровень риска (денормализованный из M2, JUGO-140)."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Допустимые переходы: откуда -> куда. Гарантирует консистентность воронки.
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
    stage: str = "new"
    origin: str = "incoming"


@dataclass(frozen=True)
class StageChanged(DomainEvent):
    application_id: UUID = field(default_factory=uuid4)
    from_stage_id: str | None = None
    to_stage_id: str = ""
    candidate_id: UUID = field(default_factory=uuid4)
    vacancy_id: UUID = field(default_factory=uuid4)
    reason: str = ""


@dataclass(frozen=True)
class ApplicationRejected(DomainEvent):
    """Событие: заявка отклонена (JUGO-140)."""

    application_id: UUID = field(default_factory=uuid4)
    candidate_id: UUID = field(default_factory=uuid4)
    vacancy_id: UUID = field(default_factory=uuid4)
    reason_code: str = ""
    reason_label: str = ""


@dataclass
class StageTransitionRecord:
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
    - Отказ требует официальной причины (reason_code).
    - Повторный отклик разрешён только если предыдущий терминальный (JUGO-142).
    """

    # non-default поля — первыми
    id: UUID
    candidate_id: CandidateId
    vacancy_id: VacancyId
    tenant_id: TenantId
    # default поля — после
    stage: ApplicationStage = ApplicationStage.NEW
    origin: ApplicationOrigin = ApplicationOrigin.INCOMING
    current_stage_id: UUID | None = None
    stage_entered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transitions: list[StageTransitionRecord] = field(default_factory=list)
    score: float | None = None
    score_provenance: UUID | None = None
    screening_score: float | None = None
    risk_level: RiskLevel = RiskLevel.NONE
    rejection_reason_code: str | None = None
    rejection_reason_label: str | None = None
    internal_rejection_note: str | None = None
    resume_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
        origin: ApplicationOrigin = ApplicationOrigin.INCOMING,
        resume_id: UUID | None = None,
    ) -> Application:
        app = cls(
            id=uuid4(),
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            tenant_id=tenant_id,
            stage=ApplicationStage.NEW,
            origin=origin,
            resume_id=resume_id,
            stage_entered_at=datetime.now(UTC),
        )
        app._record(
            ApplicationCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={
                    "candidate_id": str(candidate_id.value),
                    "vacancy_id": str(vacancy_id.value),
                    "origin": origin.value,
                },
                application_id=app.id,
                candidate_id=candidate_id.value,
                vacancy_id=vacancy_id.value,
                stage=ApplicationStage.NEW.value,
                origin=origin.value,
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
                f"Transition {self.stage.value} -> {to_stage.value} is not allowed"
            )

        from_stage = self.stage
        self.stage = to_stage
        self.stage_entered_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
        self.transitions.append(
            StageTransitionRecord(
                from_stage=from_stage,
                to_stage=to_stage,
                at=self.updated_at,
                reason=reason,
                ai_provenance=ai_provenance,
            )
        )
        # Clear rejection fields if leaving REJECTED
        if from_stage == ApplicationStage.REJECTED:
            self.rejection_reason_code = None
            self.rejection_reason_label = None
            self.internal_rejection_note = None
        self._record(
            StageChanged(
                event_id=uuid4(),
                occurred_at=self.updated_at,
                tenant_id=self.tenant_id.value,
                payload={},
                application_id=self.id,
                from_stage_id=from_stage.value,
                to_stage_id=to_stage.value,
                candidate_id=self.candidate_id.value,
                vacancy_id=self.vacancy_id.value,
                reason=reason,
            )
        )

    def reject(
        self,
        reason_code: str,
        reason_label: str,
        internal_note: str | None = None,
    ) -> None:
        """Отклонить заявку с официальной причиной (JUGO-140, JUGO-141).

        - reason_code: код из справочника причин отказов.
        - reason_label: человекочитаемая официальная причина.
        - internal_note: внутренняя заметка (видна только по правам signals:read).
        """
        if not reason_code.strip():
            raise ValueError("Rejection reason_code is required")
        if self.stage == ApplicationStage.REJECTED:
            return  # идемпотентность
        self.move_to(ApplicationStage.REJECTED, reason="rejected")
        self.rejection_reason_code = reason_code
        self.rejection_reason_label = reason_label
        self.internal_rejection_note = internal_note
        self._record(
            ApplicationRejected(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={
                    "reason_code": reason_code,
                    "reason_label": reason_label,
                },
                application_id=self.id,
                candidate_id=self.candidate_id.value,
                vacancy_id=self.vacancy_id.value,
                reason_code=reason_code,
                reason_label=reason_label,
            )
        )

    def set_score(self, score: float, provenance: UUID) -> None:
        """Установить AI-скоринг заявки (whitebox: ссылка на provenance)."""
        self.score = score
        self.score_provenance = provenance
        self.screening_score = score
        self.updated_at = datetime.now(UTC)

    def set_risk_level(self, level: RiskLevel) -> None:
        """Установить денормализованный уровень риска (JUGO-140)."""
        self.risk_level = level
        self.updated_at = datetime.now(UTC)

    @property
    def is_terminal(self) -> bool:
        return self.stage in TERMINAL_STAGES

    @property
    def is_rejected(self) -> bool:
        return self.stage == ApplicationStage.REJECTED

    @property
    def is_active(self) -> bool:
        """Активна ли заявка (не терминальная) — для правил повторных откликов."""
        return not self.is_terminal


class InvalidTransitionError(Exception):
    """Недопустимый переход между стадиями пайплайна."""
