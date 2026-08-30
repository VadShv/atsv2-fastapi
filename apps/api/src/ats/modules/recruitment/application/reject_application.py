"""Use case: отклонение заявки с официальной причиной (JUGO-141).

SECURE FIRST: официальная причина из справочника + внутренняя заметка по правам.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.modules.recruitment.domain.application import Application
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


class RejectApplicationInput:
    """DTO для отклонения заявки."""

    def __init__(
        self,
        application_id: UUID,
        reason_code: str,
        reason_label: str,
        internal_note: str | None = None,
    ) -> None:
        self.application_id = application_id
        self.reason_code = reason_code
        self.reason_label = reason_label
        self.internal_note = internal_note


class RejectApplicationUseCase:
    """Отклонить заявку с официальной причиной."""

    def __init__(self, applications: ApplicationRepository) -> None:
        self._applications = applications

    async def execute(
        self, tenant_id: TenantId, input_dto: RejectApplicationInput
    ) -> Result[Application]:
        app = await self._applications.get(tenant_id, input_dto.application_id)
        if app is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Заявка не найдена",
                {"application_id": str(input_dto.application_id)},
            )

        if not input_dto.reason_code.strip():
            return Result.err(
                ErrorCode.VALIDATION,
                "reason_code обязателен для отклонения",
                {"application_id": str(input_dto.application_id)},
            )

        app.reject(
            reason_code=input_dto.reason_code,
            reason_label=input_dto.reason_label,
            internal_note=input_dto.internal_note,
        )
        await self._applications.save(app)
        logger.info(
            "Application %s rejected: reason=%s",
            input_dto.application_id,
            input_dto.reason_code,
        )
        return Result.ok(app)
