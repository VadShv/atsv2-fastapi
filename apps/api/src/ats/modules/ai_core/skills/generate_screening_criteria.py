"""Скилл: генерация критериев скрининга из описания роли.

Ключевая AI-native фича: при создании вакансии ИИ анализирует описание роли и
формирует структурированные, взвешенные критерии скрининга кандидатов.
Whitebox: результат ссылается на provenance, рекрутер видит reasoning.
"""

from __future__ import annotations

import logging

from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.domain.models import AIRequest, ChatMessage, MessageRole
from ats.modules.ai_core.prompts import SCREENING_CRITERIA_V1
from ats.modules.ai_core.prompts.registry import get_prompt
from ats.modules.ai_core.prompts.schemas import ScreeningCriteriaOutput
from ats.modules.recruitment.domain.vacancy import RoleDescription
from ats.shared.ids import ProvenanceId, TenantId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


class GenerateScreeningCriteria:
    """Use case: генерация критериев скрининга.

    Поток:
    1. Рендер промпта screeninig_criteria:v1 переменными из RoleDescription.
    2. Вызов AIGateway.structured() → ScreeningCriteriaOutput.
    3. Возврат результата + provenance_id (whitebox).
    """

    SKILL = "generate_screening_criteria"

    def __init__(self, gateway: AIGateway) -> None:
        self._gateway = gateway

    async def execute(
        self, tenant_id: TenantId, role: RoleDescription
    ) -> Result[tuple[ScreeningCriteriaOutput, ProvenanceId]]:
        spec = get_prompt(SCREENING_CRITERIA_V1.id, SCREENING_CRITERIA_V1.version)

        variables = {
            "role_description": role.description,
            "vacancy_title": role.title,
            "seniority": role.seniority.value,
            "team": role.team,
        }
        user_text, input_hash = spec.render(variables)

        request = AIRequest(
            tenant_id=tenant_id,
            prompt_id=spec.id,
            prompt_version=spec.version,
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=spec.system),
                ChatMessage(role=MessageRole.USER, content=user_text),
            ],
            model=spec.model_hint,
            temperature=spec.temperature,
            skill=self.SKILL,
            input_refs={"input_hash": input_hash, "vacancy_title": role.title},
            variables=variables,
        )

        try:
            response = await self._gateway.structured(request, ScreeningCriteriaOutput)
        except Exception as exc:
            logger.error("Screening criteria generation failed: %s", exc)
            return Result.err(
                ErrorCode.AI_UNAVAILABLE,
                "Не удалось сгенерировать критерии скрининга",
                {"skill": self.SKILL, "error": str(exc)},
            )

        return Result.ok((response.parsed, response.provenance_id))
