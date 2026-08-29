"""Скилл: AI-парсинг резюме в структурированную карточку кандидата.

AI NATIVE: загрузил резюме → ИИ извлёк профиль → создал Candidate.
WHITEBOX: результат ссылается на provenance (модель, промпт, вход, reasoning).
"""

from __future__ import annotations

import logging

from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.domain.models import AIRequest, ChatMessage, MessageRole
from ats.modules.ai_core.prompts import PARSE_RESUME_V1
from ats.modules.ai_core.prompts.registry import get_prompt
from ats.modules.candidates.domain.parsed_resume import ParsedResume
from ats.shared.ids import ProvenanceId, TenantId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


class ParseResume:
    """Use case: AI-парсинг резюме.

    Поток:
    1. Рендер промпта parse_resume:v1 сырым текстом резюме.
    2. Вызов AIGateway.structured() → ParsedResume.
    3. Возврат результата + provenance_id (whitebox).
    """

    SKILL = "parse_resume"

    def __init__(self, gateway: AIGateway) -> None:
        self._gateway = gateway

    async def execute(
        self, tenant_id: TenantId, resume_text: str
    ) -> Result[tuple[ParsedResume, ProvenanceId]]:
        if not resume_text.strip():
            return Result.err(ErrorCode.VALIDATION, "Пустой текст резюме")

        spec = get_prompt(PARSE_RESUME_V1.id, PARSE_RESUME_V1.version)
        variables = {"resume_text": resume_text}
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
            input_refs={
                "input_hash": input_hash,
                "resume_length": str(len(resume_text)),
            },
            variables=variables,
        )

        try:
            response = await self._gateway.structured(request, ParsedResume)
        except Exception as exc:
            logger.error("Resume parsing failed: %s", exc)
            return Result.err(
                ErrorCode.AI_UNAVAILABLE,
                "Не удалось распарсить резюме",
                {"skill": self.SKILL, "error": str(exc)},
            )

        # Гарантируем searchable_text заполненным (fallback на summary/skills)
        parsed = response.parsed
        if not parsed.searchable_text.strip():
            parsed.searchable_text = " ".join(
                [parsed.headline, parsed.summary, *parsed.skills]
            ).strip()

        return Result.ok((parsed, response.provenance_id))
