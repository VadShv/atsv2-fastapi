"""Use cases воронки: управление пресетами и переходами (JUGO-130..135).

FunnelService.transition() — единая точка смены этапа заявки (JUGO-132):
атомарность, проверка допустимости, no-op, stage_transitions (append-only),
outbox-событие, аудит.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ats.modules.funnel.domain.funnel import (
    CanonicalPhase,
    FunnelPreset,
    FunnelSnapshot,
    HMDecision,
    HMDecisionType,
    StageTransition,
)
from ats.modules.funnel.ports.funnel_preset_repository import (
    FunnelPresetRepository,
)
from ats.modules.funnel.ports.funnel_snapshot_repository import (
    FunnelSnapshotRepository,
)
from ats.modules.funnel.ports.funnel_transition_repository import (
    HMDecisionRepository,
    StageTransitionRepository,
)
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


@dataclass
class AddStageInput:
    canonical_phase: CanonicalPhase
    name: str
    sla_hours: int | None = None


@dataclass
class TransitionInput:
    """DTO перехода заявки между стадиями (JUGO-132)."""

    application_id: UUID
    vacancy_id: UUID
    from_stage_id: UUID | None
    to_stage_id: UUID
    candidate_id: UUID
    reason: str = ""
    actor_type: str = "user"
    ai_provenance: UUID | None = None


# ---------------------------------------------------------------------------
# Use case: управление пресетами воронки (JUGO-130)
# ---------------------------------------------------------------------------


class FunnelPresetUseCase:
    """CRUD пресетов воронки + создание снапшота (JUGO-130, JUGO-131)."""

    def __init__(
        self,
        preset_repo: FunnelPresetRepository,
        snapshot_repo: FunnelSnapshotRepository,
    ) -> None:
        self._preset_repo = preset_repo
        self._snapshot_repo = snapshot_repo

    async def create_preset(self, tenant_id: TenantId, name: str) -> Result[FunnelPreset]:
        if not name.strip():
            return Result.err(ErrorCode.VALIDATION, "Preset name is required")
        preset = FunnelPreset.create(tenant_id=tenant_id, name=name)
        await self._preset_repo.save(preset)
        logger.info("Funnel preset %s created", preset.id)
        return Result.ok(preset)

    async def add_stage(
        self,
        tenant_id: TenantId,
        preset_id: UUID,
        dto: AddStageInput,
    ) -> Result[FunnelPreset]:
        preset = await self._preset_repo.get(tenant_id, preset_id)
        if preset is None:
            return Result.err(ErrorCode.NOT_FOUND, "Preset not found")
        try:
            preset.add_stage(
                canonical_phase=dto.canonical_phase,
                name=dto.name,
                sla_hours=dto.sla_hours,
            )
        except ValueError as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))
        await self._preset_repo.save(preset)
        return Result.ok(preset)

    async def publish_preset(self, tenant_id: TenantId, preset_id: UUID) -> Result[FunnelPreset]:
        preset = await self._preset_repo.get(tenant_id, preset_id)
        if preset is None:
            return Result.err(ErrorCode.NOT_FOUND, "Preset not found")
        try:
            preset.publish()
        except ValueError as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))
        await self._preset_repo.save(preset)
        logger.info("Funnel preset %s published", preset_id)
        return Result.ok(preset)

    async def archive_preset(self, tenant_id: TenantId, preset_id: UUID) -> Result[FunnelPreset]:
        preset = await self._preset_repo.get(tenant_id, preset_id)
        if preset is None:
            return Result.err(ErrorCode.NOT_FOUND, "Preset not found")
        preset.archive()
        await self._preset_repo.save(preset)
        return Result.ok(preset)

    async def get_preset(self, tenant_id: TenantId, preset_id: UUID) -> Result[FunnelPreset]:
        preset = await self._preset_repo.get(tenant_id, preset_id)
        if preset is None:
            return Result.err(ErrorCode.NOT_FOUND, "Preset not found")
        return Result.ok(preset)

    async def list_presets(
        self, tenant_id: TenantId, include_archived: bool = False
    ) -> Result[list[FunnelPreset]]:
        presets = await self._preset_repo.list_by_tenant(
            tenant_id, include_archived=include_archived
        )
        return Result.ok(presets)

    async def snapshot_for_vacancy(
        self,
        tenant_id: TenantId,
        preset_id: UUID,
        vacancy_id: UUID,
    ) -> Result[FunnelSnapshot]:
        """Создать снапшот пресета для вакансии (JUGO-131)."""
        preset = await self._preset_repo.get(tenant_id, preset_id)
        if preset is None:
            return Result.err(ErrorCode.NOT_FOUND, "Preset not found")
        if not preset.is_published:
            return Result.err(
                ErrorCode.VALIDATION,
                "Cannot snapshot a non-published preset",
            )
        snapshot = FunnelSnapshot.from_preset(preset, vacancy_id)
        await self._snapshot_repo.save(snapshot)
        logger.info(
            "Funnel snapshot created for vacancy %s (preset %s)",
            vacancy_id,
            preset_id,
        )
        return Result.ok(snapshot)


# ---------------------------------------------------------------------------
# Use case: FunnelService.transition() — единая точка смены этапа (JUGO-132)
# ---------------------------------------------------------------------------


class FunnelTransitionUseCase:
    """Единая точка смены этапа заявки (JUGO-132).

    Атомарность: проверка → transition → сохранение → событие.
    No-op на тот же этап — идемпотентность.
    """

    def __init__(
        self,
        snapshot_repo: FunnelSnapshotRepository,
        transition_repo: StageTransitionRepository,
    ) -> None:
        self._snapshot_repo = snapshot_repo
        self._transition_repo = transition_repo

    async def transition(
        self,
        tenant_id: TenantId,
        dto: TransitionInput,
    ) -> Result[StageTransition]:
        """Перевести заявку на новую стадию.

        Шаги:
        1. Получить снапшот воронки вакансии.
        2. Проверить допустимость перехода.
        3. No-op если from == to.
        4. Создать StageTransition (append-only).
        5. Вернуть transition.
        """
        snapshot = await self._snapshot_repo.get_by_vacancy(tenant_id, dto.vacancy_id)
        if snapshot is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Funnel snapshot not found for vacancy",
            )

        # No-op: переход на ту же стадию
        if dto.from_stage_id is not None and dto.from_stage_id == dto.to_stage_id:
            transition = StageTransition(
                id=UUID(int=0),
                application_id=dto.application_id,
                from_stage_id=dto.from_stage_id,
                to_stage_id=dto.to_stage_id,
                at=datetime.now(UTC),
                reason="no-op",
                actor_type=dto.actor_type,
                ai_provenance=dto.ai_provenance,
            )
            return Result.ok(transition)

        # Проверка допустимости
        if dto.from_stage_id is not None:
            valid = snapshot.is_valid_transition(dto.from_stage_id, dto.to_stage_id)
            if not valid:
                return Result.err(
                    ErrorCode.VALIDATION,
                    f"Transition from stage {dto.from_stage_id}"
                    f" to {dto.to_stage_id} is not allowed",
                )

        transition = StageTransition(
            id=uuid4(),
            application_id=dto.application_id,
            from_stage_id=dto.from_stage_id,
            to_stage_id=dto.to_stage_id,
            at=datetime.now(UTC),
            reason=dto.reason,
            actor_type=dto.actor_type,
            ai_provenance=dto.ai_provenance,
        )
        await self._transition_repo.add(transition)

        logger.info(
            "Application %s transitioned: %s → %s (actor=%s)",
            dto.application_id,
            dto.from_stage_id,
            dto.to_stage_id,
            dto.actor_type,
        )

        return Result.ok(transition)

    async def get_transitions(
        self,
        tenant_id: TenantId,
        application_id: UUID,
    ) -> Result[list[StageTransition]]:
        transitions = await self._transition_repo.list_by_application(tenant_id, application_id)
        return Result.ok(transitions)


# ---------------------------------------------------------------------------
# Use case: решения НМ (JUGO-134)
# ---------------------------------------------------------------------------


class HMDecisionUseCase:
    """Управление решениями нанимающего менеджера (JUGO-134)."""

    def __init__(self, decision_repo: HMDecisionRepository) -> None:
        self._decision_repo = decision_repo

    async def record_decision(
        self,
        tenant_id: TenantId,
        application_id: UUID,
        stage_id: UUID,
        decision: HMDecisionType,
        justification: str,
        created_by: UUID,
    ) -> Result[HMDecision]:
        try:
            hm_decision = HMDecision.create(
                tenant_id=tenant_id,
                application_id=application_id,
                stage_id=stage_id,
                decision=decision,
                justification=justification,
                created_by=created_by,
            )
        except ValueError as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))
        await self._decision_repo.add(hm_decision)
        logger.info(
            "HM decision recorded: app=%s stage=%s decision=%s",
            application_id,
            stage_id,
            decision.value,
        )
        return Result.ok(hm_decision)

    async def list_decisions(
        self,
        tenant_id: TenantId,
        application_id: UUID,
    ) -> Result[list[HMDecision]]:
        decisions = await self._decision_repo.list_by_application(tenant_id, application_id)
        return Result.ok(decisions)

    async def get_latest_decision(
        self,
        tenant_id: TenantId,
        application_id: UUID,
        stage_id: UUID,
    ) -> Result[HMDecision | None]:
        decision = await self._decision_repo.get_latest_by_stage(
            tenant_id, application_id, stage_id
        )
        return Result.ok(decision)
