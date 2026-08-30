"""Порт: репозиторий переходов и решений НМ (JUGO-132, JUGO-134)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.funnel.domain.funnel import HMDecision, StageTransition
from ats.shared.ids import TenantId


@runtime_checkable
class StageTransitionRepository(Protocol):
    """Append-only журнал переходов по стадиям (JUGO-132)."""

    async def add(self, transition: StageTransition) -> UUID: ...

    async def list_by_application(
        self, tenant_id: TenantId, application_id: UUID
    ) -> list[StageTransition]: ...


@runtime_checkable
class HMDecisionRepository(Protocol):
    """Репозиторий решений нанимающего менеджера (JUGO-134)."""

    async def add(self, decision: HMDecision) -> UUID: ...

    async def list_by_application(
        self, tenant_id: TenantId, application_id: UUID
    ) -> list[HMDecision]: ...

    async def get_latest_by_stage(
        self, tenant_id: TenantId, application_id: UUID, stage_id: UUID
    ) -> HMDecision | None: ...
