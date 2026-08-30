"""Порт: репозиторий снапшотов воронки (JUGO-131)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.funnel.domain.funnel import FunnelSnapshot
from ats.shared.ids import TenantId


@runtime_checkable
class FunnelSnapshotRepository(Protocol):
    """Репозиторий снапшотов воронки: immutable, привязан к вакансии."""

    async def save(self, snapshot: FunnelSnapshot) -> UUID: ...

    async def get_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: UUID
    ) -> FunnelSnapshot | None: ...
