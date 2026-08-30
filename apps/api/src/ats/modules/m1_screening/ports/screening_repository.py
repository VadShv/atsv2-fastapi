"""Порт: репозиторий результатов скрининга (гексагонал).

Домен/application зависит от интерфейса, реализация — в infra (in-memory / pg).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.m1_screening.domain.screening import ScreeningResult
from ats.shared.ids import ApplicationId, TenantId


@runtime_checkable
class ScreeningResultRepository(Protocol):
    """Репозиторий: сохранение и чтение результатов скрининга."""

    async def save(self, result: ScreeningResult) -> UUID:
        """Сохранить результат (insert или update по id)."""
        ...

    async def get(self, tenant_id: TenantId, screening_id: UUID) -> ScreeningResult | None:
        """Получить результат по id."""
        ...

    async def get_by_application(
        self, tenant_id: TenantId, application_id: ApplicationId
    ) -> ScreeningResult | None:
        """Получить актуальный результат скрининга для заявки."""
        ...

    async def list_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[ScreeningResult]:
        """Список результатов скрининга для вакансии."""
        ...

    async def list_stale(self, tenant_id: TenantId, vacancy_id: UUID) -> list[ScreeningResult]:
        """Список устаревших результатов (is_stale=True) для вакансии."""
        ...
