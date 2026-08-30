"""Порты AI Core: провенанс-ledger и репозиторий AI-артефактов.

Порты — интерфейсы, которые домен определяет, а infra реализует.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.modules.ai_core.domain.models import ProvenanceRecord
from ats.shared.ids import ProvenanceId, TenantId


@runtime_checkable
class ProvenanceLedger(Protocol):
    """Порт: хранилище провенанса (whitebox AI). Append-only."""

    async def append(self, record: ProvenanceRecord) -> ProvenanceId:
        """Записать факт AI-вызова. Idempotent по provenance_id."""
        ...

    async def get(
        self, tenant_id: TenantId, provenance_id: ProvenanceId
    ) -> ProvenanceRecord | None:
        """Получить запись провенанса для объяснения решения."""
        ...

    async def mark_verified(self, tenant_id: TenantId, provenance_id: ProvenanceId) -> None:
        """Отметить как проверенное человеком (human_verified)."""
        ...
