"""Use case: создание заявки — привязка кандидата к вакансии.

Рекрутер добавляет кандидата на вакансию → создаётся Application в стадии NEW.
"""

from __future__ import annotations

import logging

from ats.modules.recruitment.domain.application import Application
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, VacancyId
from ats.shared.result import Result

logger = logging.getLogger(__name__)


class CreateApplicationUseCase:
    """Создать заявку (кандидат → вакансия)."""

    def __init__(self, applications: ApplicationRepository) -> None:
        self._applications = applications

    async def execute(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
        idempotency_key: IdempotencyKey,
    ) -> Result[Application]:
        # Идемпотентность: если заявка уже есть — возвращаем существующую
        existing = await self._applications.find_by_candidate_and_vacancy(
            tenant_id, candidate_id, vacancy_id
        )
        if existing is not None:
            return Result.ok(existing)

        application = Application.create(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
        )
        await self._applications.save(application)
        logger.info(
            "Application created: candidate=%s vacancy=%s",
            candidate_id,
            vacancy_id,
        )
        return Result.ok(application)
