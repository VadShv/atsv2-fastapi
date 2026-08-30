"""Use case: управление версионируемыми критериями вакансии (JUGO-121).

Создание новой версии критериев (из AI-генерации или вручную),
активация версии, получение активной версии.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from ats.modules.recruitment.domain.requirement_set import (
    RequirementOrigin,
    RequirementSet,
)
from ats.modules.recruitment.ports.requirement_set_repository import (
    RequirementSetRepository,
)
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.shared.ids import TenantId, VacancyId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


@dataclass
class CreateRequirementSetInput:
    """DTO создания новой версии критериев."""

    vacancy_id: VacancyId
    criteria: dict  # ScreeningCriteriaOutput as dict
    origin: RequirementOrigin = RequirementOrigin.AI
    provenance_id: UUID | None = None
    created_by: UUID | None = None


@dataclass
class CreateRequirementSetResult:
    """Результат создания версии критериев."""

    requirement_set: RequirementSet


class RequirementSetUseCase:
    """Управление версионируемыми критериями скрининга вакансии.

    - create: создать новую версию (DRAFT)
    - activate: активировать версию (с авто-архивацией предыдущей активной)
    - get_active: получить текущую активную версию
    - list_versions: список всех версий
    """

    def __init__(
        self,
        req_repo: RequirementSetRepository,
        vacancy_repo: VacancyRepository,
    ) -> None:
        self._req_repo = req_repo
        self._vacancy_repo = vacancy_repo

    async def create(
        self,
        tenant_id: TenantId,
        dto: CreateRequirementSetInput,
    ) -> Result[CreateRequirementSetResult]:
        """Создать новую версию критериев (статус = DRAFT)."""
        # Проверить существование вакансии
        vacancy = await self._vacancy_repo.get(tenant_id, dto.vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        version_number = await self._req_repo.get_next_version_number(tenant_id, dto.vacancy_id)

        req_set = RequirementSet.create(
            tenant_id=tenant_id,
            vacancy_id=dto.vacancy_id,
            version_number=version_number,
            criteria=dto.criteria,
            origin=dto.origin,
            provenance_id=dto.provenance_id,
            created_by=dto.created_by,
        )
        await self._req_repo.save(req_set)

        logger.info(
            "RequirementSet v%d created for vacancy %s (origin=%s)",
            version_number,
            dto.vacancy_id,
            dto.origin.value,
        )

        return Result.ok(CreateRequirementSetResult(requirement_set=req_set))

    async def activate(
        self,
        tenant_id: TenantId,
        vacancy_id: VacancyId,
        set_id: UUID,
    ) -> Result[RequirementSet]:
        """Активировать версию критериев (архивирует предыдущую активную)."""
        req_set = await self._req_repo.get(tenant_id, set_id)
        if req_set is None:
            return Result.err(ErrorCode.NOT_FOUND, "Requirement set not found")

        if str(req_set.vacancy_id.value) != str(vacancy_id.value):
            return Result.err(
                ErrorCode.VALIDATION,
                "Requirement set does not belong to this vacancy",
            )

        # Архивировать предыдущую активную версию
        await self._req_repo.deactivate_active(tenant_id, vacancy_id)

        # Активировать новую
        req_set.activate()
        await self._req_repo.save(req_set)

        logger.info(
            "RequirementSet v%d activated for vacancy %s",
            req_set.version_number,
            vacancy_id,
        )

        return Result.ok(req_set)

    async def get_active(
        self,
        tenant_id: TenantId,
        vacancy_id: VacancyId,
    ) -> Result[RequirementSet | None]:
        """Получить активную версию критериев вакансии."""
        active = await self._req_repo.get_active(tenant_id, vacancy_id)
        return Result.ok(active)

    async def list_versions(
        self,
        tenant_id: TenantId,
        vacancy_id: VacancyId,
    ) -> Result[list[RequirementSet]]:
        """Список всех версий критериев вакансии."""
        versions = await self._req_repo.list_by_vacancy(tenant_id, vacancy_id)
        return Result.ok(versions)
