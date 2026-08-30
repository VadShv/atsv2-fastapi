"""Use case: создание заявки — привязка кандидата к вакансии.

Рекрутер добавляет кандидата на вакансию → создаётся Application в стадии NEW.
JUGO-140: origin и resume_id параметры.
JUGO-142: правила повторных откликов (active → CONFLICT, terminal → новый разрешён).
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.modules.recruitment.domain.application import Application, ApplicationOrigin
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, VacancyId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


class CreateApplicationUseCase:
    """Создать заявку (кандидат → вакансия) с правилами повторных откликов."""

    def __init__(self, applications: ApplicationRepository) -> None:
        self._applications = applications

    async def execute(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
        idempotency_key: IdempotencyKey,
        origin: ApplicationOrigin = ApplicationOrigin.INCOMING,
        resume_id: UUID | None = None,
    ) -> Result[Application]:
        existing = await self._applications.find_by_candidate_and_vacancy(
            tenant_id, candidate_id, vacancy_id
        )
        # JUGO-142: активная заявка → CONFLICT; терминальная → создаём новую
        if existing is not None and existing.is_active:
            return Result.err(
                ErrorCode.CONFLICT,
                "Кандидат уже имеет активную заявку на эту вакансию",
                {
                    "candidate_id": str(candidate_id.value),
                    "vacancy_id": str(vacancy_id.value),
                    "existing_application_id": str(existing.id),
                    "stage": existing.stage.value,
                },
            )

        application = Application.create(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            origin=origin,
            resume_id=resume_id,
        )
        await self._applications.save(application)
        logger.info(
            "Application created: candidate=%s vacancy=%s origin=%s",
            candidate_id,
            vacancy_id,
            origin.value,
        )
        return Result.ok(application)
