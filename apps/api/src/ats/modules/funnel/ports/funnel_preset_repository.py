"""Порт: репозиторий пресетов воронки (JUGO-130)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.funnel.domain.funnel import FunnelPreset
from ats.shared.ids import TenantId


@runtime_checkable
class FunnelPresetRepository(Protocol):
    """Репозиторий пресетов воронки: CRUD + поиск опубликованных."""

    async def save(self, preset: FunnelPreset) -> UUID: ...

    async def get(self, tenant_id: TenantId, preset_id: UUID) -> FunnelPreset | None: ...

    async def list_by_tenant(
        self, tenant_id: TenantId, include_archived: bool = False
    ) -> list[FunnelPreset]: ...

    async def get_default(self, tenant_id: TenantId) -> FunnelPreset | None:
        """Получить дефолтный пресет (для сидов)."""
        ...
