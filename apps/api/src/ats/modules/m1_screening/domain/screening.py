"""M1 Screening — домен: результат скрининга кандидата.

E-40 (JUGO-400): каркас модуля m1_screening.
Центральный агрегат: ScreeningResult — оценка кандидата по критериям вакансии.

Поток скрининга (JUGO-403..405):
  Уровень 0 — детерминированные правила очистки (дубликат, спам, дисквалификаторы)
  Уровень 1 — AI-скоринг по утверждённым критериям (0/0.5/1 × вес, цитата, объяснение)

Whitebox: каждый результат ссылается на provenance (reasoning доступен рекрутеру).
Устойчивость: AI-ошибки → non_ai_fallback; детерминированный скоринг при сбое LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import (
    ApplicationId,
    CandidateId,
    ProvenanceId,
    ScreeningResultId,
    TenantId,
    VacancyId,
)

# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------


class ScreeningRecommendation(StrEnum):
    """Итоговая рекомендация скрининга."""

    STRONG_YES = "strong_yes"
    YES = "yes"
    BORDERLINE = "borderline"
    NO = "no"
    STRONG_NO = "strong_no"
    REJECTED_LEVEL0 = "rejected_level0"  # отсев на уровне 0 (до AI)


class CriterionScore(StrEnum):
    """Оценка по одному критерию: 0 / 0.5 / 1 (дискретная шкала)."""

    FAIL = "0"
    PARTIAL = "0.5"
    PASS = "1"


class ScreeningStatus(StrEnum):
    """Статус результата скрининга."""

    PENDING = "pending"
    COMPLETED = "completed"
    STALE = "stale"  # критерии или резюме изменились → нужен перескрининг
    OVERRIDDEN = "overridden"  # рекрутер подтвердил/оспорил


class OverrideAction(StrEnum):
    """Действие рекрутера при override (JUGO-407)."""

    CONFIRM = "confirm"
    DISPUTE = "dispute"


# ---------------------------------------------------------------------------
# Доменные события
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScreeningCompleted(DomainEvent):
    """JUGO-410: скрининг завершён."""

    screening_id: UUID = field(default_factory=uuid4)
    application_id: UUID = field(default_factory=uuid4)
    candidate_id: UUID = field(default_factory=uuid4)
    vacancy_id: UUID = field(default_factory=uuid4)
    total_score: float = 0.0
    recommendation: str = "borderline"
    confidence: float | None = None
    provenance_id: UUID | None = None
    non_ai: bool = False


@dataclass(frozen=True)
class ScreeningOverridden(DomainEvent):
    """JUGO-407: рекрутер подтвердил/оспорил результат."""

    screening_id: UUID = field(default_factory=uuid4)
    application_id: UUID = field(default_factory=uuid4)
    action: str = "confirm"
    overridden_by: str = ""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionEvaluation:
    """Оценка одного критерия скрининга (JUGO-404).

    score: 0 / 0.5 / 1 (дискретная шкала).
    weight: вес критерия (из ScreeningCriteriaOutput).
    evidence: цитата из резюме, подтверждающая оценку (whitebox).
    explanation: почему такая оценка (whitebox).
    """

    criterion_name: str
    category: str
    score: float  # 0.0 | 0.5 | 1.0
    weight: float
    evidence: str = ""
    explanation: str = ""
    must_have: bool = False


@dataclass(frozen=True)
class Level0Result:
    """Результат уровня 0 — детерминированные правила очистки (JUGO-403).

    Если rejected=True, скрининг останавливается: кандидат отсекается без AI.
    """

    rejected: bool
    reason: str = ""
    matched_rules: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Агрегат: ScreeningResult
# ---------------------------------------------------------------------------


@dataclass
class ScreeningResult(AggregateRoot):
    """Агрегат: результат скрининга кандидата по критериям вакансии.

    Инварианты:
    - total_score = sum(score * weight) / sum(weight) для всех критериев.
    - must_have fail → recommendation не может быть выше NO.
    - level0_rejected → recommendation = REJECTED_LEVEL0, evaluations пуст.
    - is_stale=True при смене версии критериев или резюме.
    """

    # non-default поля
    id: ScreeningResultId
    tenant_id: TenantId
    application_id: ApplicationId
    candidate_id: CandidateId
    vacancy_id: VacancyId
    # default поля
    status: ScreeningStatus = ScreeningStatus.PENDING
    total_score: float = 0.0
    recommendation: ScreeningRecommendation = ScreeningRecommendation.BORDERLINE
    confidence: float | None = None
    evaluations: list[CriterionEvaluation] = field(default_factory=list)
    level0: Level0Result | None = None
    provenance_id: ProvenanceId | None = None
    criteria_provenance_id: ProvenanceId | None = None
    summary: str = ""
    non_ai: bool = False
    overridden_by: str = ""
    override_action: OverrideAction | None = None
    is_stale: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    _events: list[DomainEvent] = field(default_factory=list)

    # --- Фабрики ---

    @classmethod
    def create_level0_reject(
        cls,
        *,
        tenant_id: TenantId,
        application_id: ApplicationId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
        level0: Level0Result,
    ) -> ScreeningResult:
        """Создать результат с отсевом на уровне 0 (без AI)."""
        now = datetime.now(UTC)
        result = cls(
            id=ScreeningResultId.generate(),
            tenant_id=tenant_id,
            application_id=application_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            status=ScreeningStatus.COMPLETED,
            total_score=0.0,
            recommendation=ScreeningRecommendation.REJECTED_LEVEL0,
            level0=level0,
            completed_at=now,
            non_ai=False,
        )
        result._emit_completed()
        return result

    @classmethod
    def create_completed(
        cls,
        *,
        tenant_id: TenantId,
        application_id: ApplicationId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
        evaluations: list[CriterionEvaluation],
        criteria_provenance_id: ProvenanceId | None,
        provenance_id: ProvenanceId | None,
        summary: str,
        confidence: float | None = None,
        non_ai: bool = False,
    ) -> ScreeningResult:
        """Создать завершённый результат AI-скрининга."""
        total_score = _compute_total_score(evaluations)
        recommendation = _derive_recommendation(total_score, evaluations)
        now = datetime.now(UTC)
        result = cls(
            id=ScreeningResultId.generate(),
            tenant_id=tenant_id,
            application_id=application_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            status=ScreeningStatus.COMPLETED,
            total_score=total_score,
            recommendation=recommendation,
            confidence=confidence,
            evaluations=evaluations,
            criteria_provenance_id=criteria_provenance_id,
            provenance_id=provenance_id,
            summary=summary,
            non_ai=non_ai,
            completed_at=now,
        )
        result._emit_completed()
        return result

    # --- Мутации ---

    def mark_stale(self) -> None:
        """Пометить как устаревший (смена критериев/резюме). JUGO-408."""
        self.is_stale = True
        self.status = ScreeningStatus.STALE
        self.updated_at = datetime.now(UTC)

    def override(self, action: OverrideAction, user_id: str) -> None:
        """Подтвердить/оспорить результат. JUGO-407."""
        self.override_action = action
        self.overridden_by = user_id
        self.status = ScreeningStatus.OVERRIDDEN
        self.updated_at = datetime.now(UTC)
        self._record(
            ScreeningOverridden(
                event_id=uuid4(),
                occurred_at=self.updated_at,
                tenant_id=self.tenant_id.value,
                payload={"action": action.value, "user_id": user_id},
                screening_id=self.id.value,
                application_id=self.application_id.value,
                action=action.value,
                overridden_by=user_id,
            )
        )

    # --- Внутренние ---

    def _emit_completed(self) -> None:
        now = datetime.now(UTC)
        self._record(
            ScreeningCompleted(
                event_id=uuid4(),
                occurred_at=now,
                tenant_id=self.tenant_id.value,
                payload={
                    "total_score": self.total_score,
                    "recommendation": self.recommendation.value,
                },
                screening_id=self.id.value,
                application_id=self.application_id.value,
                candidate_id=self.candidate_id.value,
                vacancy_id=self.vacancy_id.value,
                total_score=self.total_score,
                recommendation=self.recommendation.value,
                confidence=self.confidence,
                provenance_id=self.provenance_id.value if self.provenance_id else None,
                non_ai=self.non_ai,
            )
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "screening_id": str(self.id.value),
            "application_id": str(self.application_id.value),
            "total_score": self.total_score,
            "recommendation": self.recommendation.value,
        }


# ---------------------------------------------------------------------------
# Чистые функции скоринга (тестируемые, детерминированные)
# ---------------------------------------------------------------------------


def _compute_total_score(evaluations: list[CriterionEvaluation]) -> float:
    """Финальный балл = sum(score * weight) / sum(weight), нормированный к [0, 1].

    Учитывает must_have: если хотя бы один must_have fail (score=0),
    общий балл домножается на 0 (жёсткий дисквалификатор).
    """
    if not evaluations:
        return 0.0
    total_weight = sum(e.weight for e in evaluations)
    if total_weight == 0:
        return 0.0
    weighted = sum(e.score * e.weight for e in evaluations)
    score = weighted / total_weight
    # Жёсткий дисквалификатор: любой must_have fail → 0
    for ev in evaluations:
        if ev.must_have and ev.score == 0.0:
            return 0.0
    return round(score, 4)


def _derive_recommendation(
    total_score: float, evaluations: list[CriterionEvaluation]
) -> ScreeningRecommendation:
    """Вывести рекомендацию из total_score.

    Пороги (JUGO-409):
    - any must_have fail → STRONG_NO
    - score >= 0.8 → STRONG_YES
    - score >= 0.6 → YES
    - score >= 0.4 → BORDERLINE
    - score > 0 → NO
    - score == 0 → STRONG_NO
    """
    has_must_have_fail = any(ev.must_have and ev.score == 0.0 for ev in evaluations)
    if has_must_have_fail:
        return ScreeningRecommendation.STRONG_NO
    if total_score >= 0.8:
        return ScreeningRecommendation.STRONG_YES
    if total_score >= 0.6:
        return ScreeningRecommendation.YES
    if total_score >= 0.4:
        return ScreeningRecommendation.BORDERLINE
    if total_score > 0.0:
        return ScreeningRecommendation.NO
    return ScreeningRecommendation.STRONG_NO


# JUGO-409: пороговые правила для авто-перехода
THRESHOLD_AUTO_ADVANCE: float = 0.6  # score >= X → авто-переход на screening→interview
THRESHOLD_AUTO_REJECT: float = 0.2  # score <= Y → очередь «на отсев»
