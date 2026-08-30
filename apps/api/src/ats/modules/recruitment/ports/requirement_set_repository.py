"""Порт: репозиторий версионируемых наборов критериев (JUGO-121)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.recruitment.domain.requirement_set import RequirementSet
from ats.shared.ids import TenantId, VacancyId


@runtime_checkable
class RequirementSetRepository(Protocol):
    """Репозиторий наборов критериев: версионирование + активация."""

    async def save(self, req_set: RequirementSet) -> UUID:
        """Сохранить (создать или обновить) версию критериев."""
        ...

    async def get(self, tenant_id: TenantId, set_id: UUID) -> RequirementSet | None:
        """Получить версию по id."""
        ...

    async def list_by_vacancy(
        self, tenant_id: TenantId, vacancy_id: VacancyId
    ) -> list[RequirementSet]:
        """Список всех версий критериев вакансии (включая архивные)."""
        ...

    async def get_active(self, tenant_id: TenantId, vacancy_id: VacancyId) -> RequirementSet | None:
        """Получить активную версию критериев вакансии (или None)."""
        ...

    async def get_next_version_number(self, tenant_id: TenantId, vacancy_id: VacancyId) -> int:
        """Следующий номер версии для вакансии."""
        ...

    async def deactivate_active(self, tenant_id: TenantId, vacancy_id: VacancyId) -> None:
        """Снять статус ACTIVE с текущей активной версии (перед активацией новой)."""
        ...
