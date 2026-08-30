"""Домен воронки: этапы как данные (JUGO-130..135).

Центральный контракт системы: пайплайн найма настраивается per-tenant через
пресеты (funnel_presets). Пресет — упорядоченный набор стадий (funnel_stages),
каждая стадия привязана к канонической фазе (canonical_phase).

Канонические фазы — фиксированный набор, на который завязаны автоматизации,
аналитика и модули (M1 screening, M2 risk и т.д.).

JUGO-130: модели funnel_presets, funnel_stages + сиды дефолтного пресета.
JUGO-131: снапшот пресета на вакансию при публикации.
JUGO-132: FunnelService.transition() — единая точка смены этапа.
JUGO-134: hm_decisions — неизменяемое решение НМ.
JUGO-135: stage_automation — каркас правил автоперехода.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import TenantId

# ---------------------------------------------------------------------------
# Канонические фазы (фиксированный набор — ТЗ §5, §8.1)
# ---------------------------------------------------------------------------


class CanonicalPhase(StrEnum):
    """Канонические фазы пайплайна. На них завязаны модули и аналитика.

    Каждая стадия в пресете привязана к одной канонической фазе.
    Множество стадий может маппиться на одну фазу (подэтапы).
    """

    NEW = "new"  # новый отклик
    SCREENING = "screening"  # скрининг (M1)
    INTERVIEW = "interview"  # интервью
    OFFER = "offer"  # оффер
    HIRED = "hired"  # нанят (терминальная)
    REJECTED = "rejected"  # отказ (терминальная)


class StageCategory(StrEnum):
    """Категория стадии для логики прав и автоматизаций."""

    INTAKE = "intake"  # приём заявок
    ASSESSMENT = "assessment"  # оценка
    DECISION = "decision"  # решение
    TERMINAL = "terminal"  # терминальная (найм/отказ)


TERMINAL_CANONICAL_PHASES = frozenset({CanonicalPhase.HIRED, CanonicalPhase.REJECTED})


# ---------------------------------------------------------------------------
# JUGO-130: FunnelPreset + FunnelStage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunnelPresetCreated(DomainEvent):
    """Событие: создан пресет воронки."""

    preset_id: UUID = field(default_factory=uuid4)
    name: str = ""


@dataclass(frozen=True)
class FunnelPresetPublished(DomainEvent):
    """Событие: пресет воронки опубликован (доступен для привязки к вакансиям)."""

    preset_id: UUID = field(default_factory=uuid4)
    name: str = ""


@dataclass
class FunnelStage:
    """Стадия в пресете воронки (JUGO-130).

    - canonical_phase: привязка к канонической фазе (для модулей/аналитики).
    - category: категория для логики прав и автоматизаций.
    - order_no: позиция в пайплайне (0, 1, 2...).
    - sla_hours: SLA пребывания на стадии (для алертов).
    - substages: подэтапы (опционально, для детализации внутри стадии).
    - is_terminal: терминальная стадия (найм/отказ).
    """

    id: UUID
    canonical_phase: CanonicalPhase
    name: str
    order_no: int
    category: StageCategory = StageCategory.INTAKE
    sla_hours: int | None = None
    substages: list[str] = field(default_factory=list)
    is_terminal: bool = False

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "canonical_phase": self.canonical_phase.value,
            "name": self.name,
            "order_no": self.order_no,
            "category": self.category.value,
            "sla_hours": self.sla_hours,
            "substages": list(self.substages),
            "is_terminal": self.is_terminal,
        }


class FunnelPresetStatus(StrEnum):
    """Статус пресета воронки."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass
class FunnelPreset(AggregateRoot):
    """Пресет воронки — настраиваемый пайплайн найма (JUGO-130).

    Инварианты:
    - Пресет содержит упорядоченный набор стадий.
    - Каждая стадия привязана к канонической фазе.
    - Пресет можно опубликовать (publish) — после этого он доступен для
      привязки к вакансиям. Снапшот публ. пресета неизменяем (JUGO-131).
    - В пресете есть хотя бы одна терминальная стадия (HIRED или REJECTED).
    - order_no уникальны и монотонны в пределах пресета.
    """

    id: UUID
    tenant_id: TenantId
    name: str
    stages: list[FunnelStage] = field(default_factory=list)
    status: FunnelPresetStatus = FunnelPresetStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        name: str,
        stages: list[FunnelStage] | None = None,
    ) -> FunnelPreset:
        """Создать пресет (статус = DRAFT)."""
        preset = cls(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            stages=list(stages) if stages else [],
        )
        preset._record(
            FunnelPresetCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={"name": name},
                preset_id=preset.id,
                name=name,
            )
        )
        return preset

    def add_stage(
        self,
        canonical_phase: CanonicalPhase,
        name: str,
        category: StageCategory = StageCategory.INTAKE,
        sla_hours: int | None = None,
        substages: list[str] | None = None,
    ) -> FunnelStage:
        """Добавить стадию в пресет. Авто-расчёт order_no."""
        if self.status != FunnelPresetStatus.DRAFT:
            raise ValueError("Cannot add stages to a published/archived preset")
        order_no = max((s.order_no for s in self.stages), default=-1) + 1
        is_terminal = canonical_phase in TERMINAL_CANONICAL_PHASES
        stage = FunnelStage(
            id=uuid4(),
            canonical_phase=canonical_phase,
            name=name,
            order_no=order_no,
            category=category,
            sla_hours=sla_hours,
            substages=substages or [],
            is_terminal=is_terminal,
        )
        self.stages.append(stage)
        self.updated_at = datetime.now(UTC)
        return stage

    def publish(self) -> None:
        """Опубликовать пресет — сделать доступным для привязки к вакансиям."""
        if self.status != FunnelPresetStatus.DRAFT:
            raise ValueError(f"Cannot publish preset in status {self.status.value}")
        if not self.stages:
            raise ValueError("Cannot publish empty preset")
        if not any(s.is_terminal for s in self.stages):
            raise ValueError("Preset must have at least one terminal stage")
        self.status = FunnelPresetStatus.PUBLISHED
        self.updated_at = datetime.now(UTC)
        self._record(
            FunnelPresetPublished(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={"name": self.name},
                preset_id=self.id,
                name=self.name,
            )
        )

    def archive(self) -> None:
        """Архивировать пресет (нельзя привязывать к новым вакансиям)."""
        if self.status == FunnelPresetStatus.ARCHIVED:
            return
        self.status = FunnelPresetStatus.ARCHIVED
        self.updated_at = datetime.now(UTC)

    def get_stage(self, stage_id: UUID) -> FunnelStage | None:
        return next((s for s in self.stages if s.id == stage_id), None)

    def get_first_stage(self) -> FunnelStage | None:
        if not self.stages:
            return None
        return min(self.stages, key=lambda s: s.order_no)

    @property
    def is_published(self) -> bool:
        return self.status == FunnelPresetStatus.PUBLISHED

    def to_snapshot(self) -> dict:
        """Сериализация пресета в неизменяемый снапшот (JUGO-131).

        Снапшот привязывается к вакансии при публикации и защищает
        исторические воронки от правок пресета.
        """
        return {
            "preset_id": str(self.id),
            "name": self.name,
            "stages": [s.to_dict() for s in self.stages],
        }


# ---------------------------------------------------------------------------
# JUGO-131: FunnelSnapshot — снапшот пресета на вакансию
# ---------------------------------------------------------------------------


@dataclass
class FunnelSnapshot:
    """Неизменяемый снапшот пресета воронки, привязанный к вакансии.

    Создаётся при публикации вакансии (или при создании отклика).
    Защищает исторические воронки от правок пресета: даже если пресет
    изменён/архивирован, снапшот сохраняет конфигурацию стадий на момент
    привязки.
    """

    vacancy_id: UUID
    tenant_id: TenantId
    preset_id: UUID
    stages: list[FunnelStage]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_preset(
        cls,
        preset: FunnelPreset,
        vacancy_id: UUID,
    ) -> FunnelSnapshot:
        """Создать снапшот из опубликованного пресета."""
        if not preset.is_published:
            raise ValueError("Cannot snapshot a non-published preset")
        return cls(
            vacancy_id=vacancy_id,
            tenant_id=preset.tenant_id,
            preset_id=preset.id,
            stages=list(preset.stages),
        )

    def get_stage(self, stage_id: UUID) -> FunnelStage | None:
        return next((s for s in self.stages if s.id == stage_id), None)

    def get_stage_by_canonical(self, phase: CanonicalPhase) -> FunnelStage | None:
        return next(
            (s for s in self.stages if s.canonical_phase == phase),
            None,
        )

    def get_first_stage(self) -> FunnelStage | None:
        if not self.stages:
            return None
        return min(self.stages, key=lambda s: s.order_no)

    def get_next_stage(self, current_stage_id: UUID) -> FunnelStage | None:
        """Найти следующую стадию после текущей (по order_no)."""
        current = self.get_stage(current_stage_id)
        if current is None:
            return None
        after = [s for s in self.stages if s.order_no > current.order_no]
        if not after:
            return None
        return min(after, key=lambda s: s.order_no)

    def is_valid_transition(self, from_id: UUID, to_id: UUID) -> bool:
        """Проверить допустимость перехода между стадиями.

        Правила:
        - На терминальную стадию можно перейти с любой (кроме терминальной).
        - С терминальной стадии можно перейти только на NEW (возврат).
        - Иначе — только вперёд (order_no увеличивается) или на REJECTED.
        """
        from_stage = self.get_stage(from_id)
        to_stage = self.get_stage(to_id)
        if from_stage is None or to_stage is None:
            return False
        if from_id == to_id:
            return True  # no-op

        # С терминальной — только возврат на NEW
        if from_stage.is_terminal:
            return to_stage.canonical_phase == CanonicalPhase.NEW

        # На терминальную (HIRED) — можно с любой не-терминальной
        if to_stage.is_terminal and to_stage.canonical_phase == CanonicalPhase.HIRED:
            return True

        # На REJECTED — можно с любой не-терминальной
        if to_stage.canonical_phase == CanonicalPhase.REJECTED:
            return True

        # Иначе — только вперёд
        return to_stage.order_no > from_stage.order_no


# ---------------------------------------------------------------------------
# JUGO-132: StageTransition — append-only журнал переходов
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunnelTransitionEvent(DomainEvent):
    """Событие: переход заявки между стадиями воронки (JUGO-132).

    Заменяет StageChanged из application.py — теперь стадии как данные.
    """

    application_id: UUID = field(default_factory=uuid4)
    from_stage_id: str | None = None
    to_stage_id: str = ""
    vacancy_id: UUID = field(default_factory=uuid4)
    candidate_id: UUID = field(default_factory=uuid4)
    reason: str = ""
    actor_type: str = "user"


@dataclass
class StageTransition:
    """Запись о переходе между стадиями (append-only, JUGO-132).

    - application_id: заявка, к которой относится переход.
    - from_stage_id / to_stage_id: id стадий из снапшота воронки.
    - actor_type: кто инициировал (user/system/ai_agent/integration).
    - ai_provenance: ссылка на AI-вызов (whitebox), если actor_type=ai_agent.
    """

    id: UUID
    application_id: UUID
    from_stage_id: UUID | None
    to_stage_id: UUID
    at: datetime
    reason: str = ""
    actor_type: str = "user"
    ai_provenance: UUID | None = None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "application_id": str(self.application_id),
            "from_stage_id": str(self.from_stage_id) if self.from_stage_id else None,
            "to_stage_id": str(self.to_stage_id),
            "at": self.at.isoformat(),
            "reason": self.reason,
            "actor_type": self.actor_type,
            "ai_provenance": str(self.ai_provenance) if self.ai_provenance else None,
        }


# ---------------------------------------------------------------------------
# JUGO-134: HMDecision — решение нанимающего менеджера
# ---------------------------------------------------------------------------


class HMDecisionType(StrEnum):
    """Тип решения нанимающего менеджера."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEED_INFO = "need_info"


@dataclass(frozen=True)
class HMDecisionRecorded(DomainEvent):
    """Событие: записано решение НМ (JUGO-134)."""

    application_id: UUID = field(default_factory=uuid4)
    decision: str = ""
    stage_id: UUID = field(default_factory=uuid4)


@dataclass
class HMDecision:
    """Неизменяемое решение нанимающего менеджера поверх этапа (JUGO-134).

    Инварианты:
    - Запись неизменяема (immutable). Изменение решения → новая запись.
    - Привязана к конкретной стадии (stage_id) из снапшота воронки.
    - decision: approved / rejected / need_info.
    - justification: обоснование (обязательное поле).
    - created_by: id НМ (пользователя).
    """

    id: UUID
    tenant_id: TenantId
    application_id: UUID
    stage_id: UUID
    decision: HMDecisionType
    justification: str
    created_by: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        application_id: UUID,
        stage_id: UUID,
        decision: HMDecisionType,
        justification: str,
        created_by: UUID,
    ) -> HMDecision:
        if not justification.strip():
            raise ValueError("Justification is required for HM decision")
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            application_id=application_id,
            stage_id=stage_id,
            decision=decision,
            justification=justification,
            created_by=created_by,
        )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "application_id": str(self.application_id),
            "stage_id": str(self.stage_id),
            "decision": self.decision.value,
            "justification": self.justification,
            "created_by": str(self.created_by),
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# JUGO-135: StageAutomationRule — каркас правил автоперехода
# ---------------------------------------------------------------------------


class AutomationCondition(StrEnum):
    """Условия для автоперехода (каркас, JUGO-135)."""

    SCREENING_SCORE_THRESHOLD = "screening_score_threshold"
    AI_RECOMMENDATION = "ai_recommendation"
    SLA_EXPIRED = "sla_expired"
    HM_APPROVED = "hm_approved"
    MANUAL_OVERRIDE = "manual_override"


class AutomationAction(StrEnum):
    """Действия автоперехода."""

    ADVANCE = "advance"
    REJECT = "reject"
    HOLD = "hold"


@dataclass
class StageAutomationRule:
    """Правило автоперехода: условие → действие (JUGO-135, каркас).

    - condition: тип условия (score, AI-рекомендация, SLA, HM-решение...).
    - action: что делать (продвинуть / отказать / задержать).
    - target_stage_id: стадия назначения (для advance).
    - params: параметры условия (порог скора, уверенность AI...).
    - actor_type: system (для подписи в transition).
    - enabled: включено/выключено.
    - block_conditions: блокировки автоотказа (VIP, ручное решение,
      терминальный этап, низкая уверенность AI).
    """

    id: UUID
    tenant_id: TenantId
    stage_id: UUID
    condition: AutomationCondition
    action: AutomationAction
    target_stage_id: UUID | None = None
    params: dict = field(default_factory=dict)
    enabled: bool = True
    block_auto_reject: bool = True  # блокировки автоотказа

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        stage_id: UUID,
        condition: AutomationCondition,
        action: AutomationAction,
        target_stage_id: UUID | None = None,
        params: dict | None = None,
    ) -> StageAutomationRule:
        if action == AutomationAction.ADVANCE and target_stage_id is None:
            raise ValueError("ADVANCE action requires target_stage_id")
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            stage_id=stage_id,
            condition=condition,
            action=action,
            target_stage_id=target_stage_id,
            params=params or {},
        )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "stage_id": str(self.stage_id),
            "condition": self.condition.value,
            "action": self.action.value,
            "target_stage_id": str(self.target_stage_id) if self.target_stage_id else None,
            "params": self.params,
            "enabled": self.enabled,
            "block_auto_reject": self.block_auto_reject,
        }


# ---------------------------------------------------------------------------
# Дефолтный пресет (сид) — JUGO-130
# ---------------------------------------------------------------------------


def create_default_preset(tenant_id: TenantId) -> FunnelPreset:
    """Создать дефолтный пресет воронки (аналог Huntflow).

    Стадии: Новый → Скрининг → Интервью → Оффер → Нанят / Отказ.
    """
    preset = FunnelPreset.create(tenant_id=tenant_id, name="Default Pipeline")
    preset.add_stage(
        canonical_phase=CanonicalPhase.NEW,
        name="Новый",
        category=StageCategory.INTAKE,
        sla_hours=24,
    )
    preset.add_stage(
        canonical_phase=CanonicalPhase.SCREENING,
        name="Скрининг",
        category=StageCategory.ASSESSMENT,
        sla_hours=48,
    )
    preset.add_stage(
        canonical_phase=CanonicalPhase.INTERVIEW,
        name="Интервью",
        category=StageCategory.ASSESSMENT,
        sla_hours=72,
    )
    preset.add_stage(
        canonical_phase=CanonicalPhase.OFFER,
        name="Оффер",
        category=StageCategory.DECISION,
        sla_hours=48,
    )
    preset.add_stage(
        canonical_phase=CanonicalPhase.HIRED,
        name="Нанят",
        category=StageCategory.TERMINAL,
    )
    preset.add_stage(
        canonical_phase=CanonicalPhase.REJECTED,
        name="Отказ",
        category=StageCategory.TERMINAL,
    )
    preset.publish()
    return preset
