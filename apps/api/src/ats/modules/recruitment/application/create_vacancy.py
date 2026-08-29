"""Use case: создание вакансии + AI-генерация критериев скрининга.

AI NATIVE: создание вакансии сразу триггерит генерацию критериев из описания роли.
Рекрутер получает вакансию с готовыми ИИ-критериями для accept/reject.
"""

from __future__ import annotations

import logging

from ats.modules.ai_core.skills.generate_screening_criteria import (
    GenerateScreeningCriteria,
)
from ats.modules.recruitment.domain.vacancy import (
    RoleDescription,
    Seniority,
    Vacancy,
    VacancyId,
)
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.shared.ids import IdempotencyKey, TenantId
from ats.shared.result import ErrorCode, Result, is_error

logger = logging.getLogger(__name__)


class CreateVacancyInput:
    """Входные данные создания вакансии (DTO)."""

    def __init__(
        self,
        title: str,
        seniority: Seniority,
        team: str,
        description: str,
        requirements: list[str] | None = None,
        nice_to_have: list[str] | None = None,
    ) -> None:
        self.title = title
        self.seniority = seniority
        self.team = team
        self.description = description
        self.requirements = requirements or []
        self.nice_to_have = nice_to_have or []


class CreateVacancyResult:
    """Результат: вакансия + сгенерированные критерии (если AI отработал)."""

    def __init__(
        self,
        vacancy_id: VacancyId,
        criteria_provenance_id: str | None,
        criteria: object | None,
        criteria_error: str | None,
    ) -> None:
        self.vacancy_id = vacancy_id
        self.criteria_provenance_id = criteria_provenance_id
        self.criteria = criteria
        self.criteria_error = criteria_error


class CreateVacancyUseCase:
    """Создать вакансию и сгенерировать AI-критерии скрининга.

    Вариант поведения: вакансия создаётся всегда; если AI недоступен —
    вакансия сохраняется без критериев (graceful degradation), ошибка возвращается отдельно.
    """

    def __init__(
        self,
        vacancies: VacancyRepository,
        screening_skill: GenerateScreeningCriteria,
    ) -> None:
        self._vacancies = vacancies
        self._screening_skill = screening_skill

    async def execute(
        self,
        tenant_id: TenantId,
        input_dto: CreateVacancyInput,
        idempotency_key: IdempotencyKey,
    ) -> Result[CreateVacancyResult]:
        # 1. Валидация
        if not input_dto.title.strip():
            return Result.err(ErrorCode.VALIDATION, "Title is required")
        if not input_dto.description.strip():
            return Result.err(
                ErrorCode.VALIDATION,
                "Role description is required to generate screening criteria",
            )

        # 2. Создание агрегата
        role = RoleDescription(
            title=input_dto.title,
            seniority=input_dto.seniority,
            team=input_dto.team,
            description=input_dto.description,
            requirements=input_dto.requirements,
            nice_to_have=input_dto.nice_to_have,
        )
        vacancy = Vacancy.create(tenant_id=tenant_id, role=role)

        # 3. Сохранение (с outbox-событиями)
        await self._vacancies.save(vacancy)

        # 4. AI-генерация критериев скрининга
        criteria_result = await self._screening_skill.execute(tenant_id, role)

        criteria_provenance_id: str | None = None
        criteria: object | None = None
        criteria_error: str | None = None

        if is_error(criteria_result):
            err = criteria_result.error
            criteria_error = err.message
            logger.warning(
                "Vacancy %s created without AI criteria: %s", vacancy.id, err
            )
        else:
            parsed, provenance_id = criteria_result.value
            vacancy.attach_screening_criteria(provenance_id)
            await self._vacancies.save(vacancy)
            criteria_provenance_id = str(provenance_id)
            criteria = parsed

        return Result.ok(
            CreateVacancyResult(
                vacancy_id=vacancy.id,
                criteria_provenance_id=criteria_provenance_id,
                criteria=criteria,
                criteria_error=criteria_error,
            )
        )
