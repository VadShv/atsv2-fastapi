"""Use case: CRUD вакансий + статусная машина (JUGO-120, JUGO-124).

Создание вакансии уже в create_vacancy.py (с AI-генерацией критериев).
Здесь — get, list, update, publish, close, cancel, put_on_hold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ats.modules.recruitment.domain.vacancy import (
    Vacancy,
    VacancyStatus,
)
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.shared.ids import TenantId, VacancyId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


@dataclass
class UpdateVacancyInput:
    """DTO обновления вакансии (patch-семантика)."""

    title: str | None = None
    description: str | None = None
    requirements: list[str] | None = None
    nice_to_have: list[str] | None = None
    team: str | None = None
    hiring_team: str | None = None


class VacancyCrudUseCase:
    """CRUD-операции над вакансиями + статусная машина.

    Делегирует персистентность в VacancyRepository. Возвращает Result-тип.
    """

    def __init__(self, vacancies: VacancyRepository) -> None:
        self._vacancies = vacancies

    async def get(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Result[Vacancy]:
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")
        return Result.ok(vacancy)

    async def list(
        self,
        tenant_id: TenantId,
        status: VacancyStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Result[list[Vacancy]]:
        items = await self._vacancies.list_by_tenant(tenant_id, limit, offset)
        if status is not None:
            items = [v for v in items if v.status == status]
        return Result.ok(items)

    async def update(
        self,
        tenant_id: TenantId,
        vacancy_id: VacancyId,
        dto: UpdateVacancyInput,
    ) -> Result[Vacancy]:
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        vacancy.update_role(
            title=dto.title,
            description=dto.description,
            requirements=dto.requirements,
            nice_to_have=dto.nice_to_have,
            team=dto.team,
            hiring_team=dto.hiring_team,
        )
        await self._vacancies.save(vacancy)
        return Result.ok(vacancy)

    async def publish(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Result[Vacancy]:
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        try:
            vacancy.publish()
        except ValueError as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))

        await self._vacancies.save(vacancy)
        logger.info("Vacancy %s published", vacancy_id)
        return Result.ok(vacancy)

    async def put_on_hold(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Result[Vacancy]:
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        try:
            vacancy.put_on_hold()
        except Exception as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))

        await self._vacancies.save(vacancy)
        return Result.ok(vacancy)

    async def close(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Result[Vacancy]:
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        try:
            vacancy.close()
        except Exception as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))

        await self._vacancies.save(vacancy)
        logger.info("Vacancy %s closed (hired=%d)", vacancy_id, vacancy.hired_count)
        return Result.ok(vacancy)

    async def cancel(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Result[Vacancy]:
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        try:
            vacancy.cancel()
        except Exception as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))

        await self._vacancies.save(vacancy)
        logger.info("Vacancy %s canceled", vacancy_id)
        return Result.ok(vacancy)

    async def delete(self, tenant_id: TenantId, vacancy_id: VacancyId) -> Result[bool]:
        """Удалить вакансию (только из DRAFT)."""
        vacancy = await self._vacancies.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(ErrorCode.NOT_FOUND, "Vacancy not found")

        if vacancy.status != VacancyStatus.DRAFT:
            return Result.err(
                ErrorCode.VALIDATION,
                "Can only delete vacancies in DRAFT status",
            )

        # InMemory не имеет delete, но мы можем добавить если нужно
        # Пока просто возвращаем ошибку — удаление не поддерживается
        return Result.err(
            ErrorCode.VALIDATION,
            "Vacancy deletion is not supported; use cancel instead",
        )
