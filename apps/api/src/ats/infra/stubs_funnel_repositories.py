"""In-memory репозитории воронки для dev/тестов (JUGO-130..135)."""

from __future__ import annotations

from uuid import UUID

from ats.modules.funnel.domain.funnel import (
    FunnelPreset,
    FunnelPresetStatus,
    FunnelSnapshot,
    HMDecision,
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


class InMemoryFunnelPresetRepository(FunnelPresetRepository):
    """In-memory репозиторий пресетов воронки."""

    def __init__(self) -> None:
        self._store: dict[str, FunnelPreset] = {}

    @staticmethod
    def _key(tenant_id: TenantId, preset_id: UUID) -> str:
        return f"{tenant_id.value}:{preset_id}"

    async def save(self, preset: FunnelPreset) -> UUID:
        self._store[self._key(preset.tenant_id, preset.id)] = preset
        return preset.id

    async def get(self, tenant_id: TenantId, preset_id: UUID) -> FunnelPreset | None:
        return self._store.get(self._key(tenant_id, preset_id))

    async def list_by_tenant(
        self, tenant_id: TenantId, include_archived: bool = False
    ) -> list[FunnelPreset]:
        items = [p for p in self._store.values() if str(p.tenant_id.value) == str(tenant_id.value)]
        if not include_archived:
            items = [p for p in items if p.status != FunnelPresetStatus.ARCHIVED]
        return items

    async def get_default(self, tenant_id: TenantId) -> FunnelPreset | None:
        items = await self.list_by_tenant(tenant_id)
        return next((p for p in items if p.name == "Default Pipeline"), None)


class InMemoryFunnelSnapshotRepository(FunnelSnapshotRepository):
    """In-memory репозиторий снапшотов воронки."""

    def __init__(self) -> None:
        self._store: dict[str, FunnelSnapshot] = {}

    @staticmethod
    def _key(tenant_id: TenantId, vacancy_id: UUID) -> str:
        return f"{tenant_id.value}:{vacancy_id}"

    async def save(self, snapshot: FunnelSnapshot) -> UUID:
        self._store[self._key(snapshot.tenant_id, snapshot.vacancy_id)] = snapshot
        return snapshot.vacancy_id

    async def get_by_vacancy(self, tenant_id: TenantId, vacancy_id: UUID) -> FunnelSnapshot | None:
        return self._store.get(self._key(tenant_id, vacancy_id))


class InMemoryStageTransitionRepository(StageTransitionRepository):
    """In-memory append-only журнал переходов."""

    def __init__(self) -> None:
        self._store: list[StageTransition] = []

    async def add(self, transition: StageTransition) -> UUID:
        self._store.append(transition)
        return transition.id

    async def list_by_application(
        self, tenant_id: TenantId, application_id: UUID
    ) -> list[StageTransition]:
        return [t for t in self._store if str(t.application_id) == str(application_id)]


class InMemoryHMDecisionRepository(HMDecisionRepository):
    """In-memory репозиторий решений НМ."""

    def __init__(self) -> None:
        self._store: list[HMDecision] = []

    async def add(self, decision: HMDecision) -> UUID:
        self._store.append(decision)
        return decision.id

    async def list_by_application(
        self, tenant_id: TenantId, application_id: UUID
    ) -> list[HMDecision]:
        return [
            d
            for d in self._store
            if str(d.application_id) == str(application_id)
            and str(d.tenant_id.value) == str(tenant_id.value)
        ]

    async def get_latest_by_stage(
        self, tenant_id: TenantId, application_id: UUID, stage_id: UUID
    ) -> HMDecision | None:
        decisions = [
            d
            for d in self._store
            if str(d.application_id) == str(application_id)
            and str(d.stage_id) == str(stage_id)
            and str(d.tenant_id.value) == str(tenant_id.value)
        ]
        if not decisions:
            return None
        return max(decisions, key=lambda d: d.created_at)
