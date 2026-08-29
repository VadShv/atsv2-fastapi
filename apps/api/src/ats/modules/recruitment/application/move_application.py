"""Use case: перевод заявки по пайплайну (движение кандидата по стадиям).

AI NATIVE: переход может быть инициирован AI-оценкой (ai_provenance, whitebox).
USERFRIENDLY: рекрутер переводит кандидата в один клик с указанием причины.
"""

from __future__ import annotations

import logging

from ats.modules.recruitment.domain.application import (
    Application,
    ApplicationStage,
    InvalidTransitionError,
)
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result, is_error
from uuid import UUID

logger = logging.getLogger(__name__)


class MoveApplicationInput:
    def __init__(
        self,
        application_id: UUID,
        to_stage: ApplicationStage,
        reason: str = "",
        ai_provenance: UUID | None = None,
    ) -> None:
        self.application_id = application_id
        self.to_stage = to_stage
        self.reason = reason
        self.ai_provenance = ai_provenance


class MoveApplicationUseCase:
    """Перевести заявку на новую стадию пайплайна."""

    def __init__(self, applications: ApplicationRepository) -> None:
        self._applications = applications

    async def execute(
        self, tenant_id: TenantId, input_dto: MoveApplicationInput
    ) -> Result[Application]:
        app = await self._applications.get(tenant_id, input_dto.application_id)
        if app is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Заявка не найдена",
                {"application_id": str(input_dto.application_id)},
            )

        try:
            app.move_to(
                to_stage=input_dto.to_stage,
                reason=input_dto.reason,
                ai_provenance=input_dto.ai_provenance,
            )
        except InvalidTransitionError as exc:
            return Result.err(
                ErrorCode.CONFLICT,
                str(exc),
                {"from": app.stage.value, "to": input_dto.to_stage.value},
            )

        await self._applications.save(app)
        logger.info(
            "Application %s moved to %s", input_dto.application_id, input_dto.to_stage.value
        )
        return Result.ok(app)


# is_error импортируется для проверки результата вызывающим кодом
_ = is_error
