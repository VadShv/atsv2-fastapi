"""M1 Screening — конвейер скрининга (JUGO-405).

Оркестрация:
  1. Уровень 0 — детерминированные правила очистки (level0_rules).
  2. Если не отсечён — AI-скоринг по утверждённым критериям вакансии
     (0/0.5/1 × вес, цитата, объяснение).
  3. Расчёт total_score, recommendation, confidence.
  4. Запись результата в репозиторий + доменное событие.

Устойчивость: при сбое LLM — non_ai_fallback (оценка 0, recommendation=NO).
Whitebox: результат ссылается на provenance (reasoning доступен рекрутеру).
Бюджет токенов: усечение резюме (JUGO-405).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.domain.models import AIRequest, ChatMessage, MessageRole
from ats.modules.ai_core.prompts.registry import get_prompt
from ats.modules.m1_screening.domain.level0_rules import Level0Input, run_level0
from ats.modules.m1_screening.domain.screening import (
    CriterionEvaluation,
    ScreeningResult,
)
from ats.modules.m1_screening.ports.screening_repository import (
    ScreeningResultRepository,
)
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.shared.ids import ApplicationId, CandidateId, TenantId, VacancyId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)

# Промпт m1.screening.score (JUGO-404)
SCREENING_SCORE_PROMPT_ID = "m1_screening_score"
SCREENING_SCORE_PROMPT_VERSION = "1.0.0"

# Бюджет токенов: усечение резюме (JUGO-405)
MAX_RESUME_CHARS = 8000


class ScreenCandidateUseCase:
    """Use case: скрининг кандидата по критериям вакансии.

    Зависимости:
    - screening_repo: сохранение результатов
    - vacancy_repo: чтение вакансии + критериев (provenance)
    - gateway: AI-скоринг (structured output)
    - provenance_ledger: чтение утверждённых критериев (ScreeningCriteriaOutput)
    """

    SKILL = "m1_screening_score"

    def __init__(
        self,
        screening_repo: ScreeningResultRepository,
        vacancy_repo: VacancyRepository,
        gateway: AIGateway,
        provenance_ledger: Any,
    ) -> None:
        self._repo = screening_repo
        self._vacancy_repo = vacancy_repo
        self._gateway = gateway
        self._provenance = provenance_ledger

    async def execute(
        self,
        tenant_id: TenantId,
        application_id: ApplicationId,
        candidate_id: CandidateId,
        vacancy_id: VacancyId,
        resume_text: str,
        *,
        is_blacklisted: bool = False,
        is_duplicate: bool = False,
        hard_disqualify_reasons: list[str] | None = None,
    ) -> Result[ScreeningResult]:
        """Запустить конвейер скрининга для заявки.

        Возвращает ScreeningResult (level0-reject или completed AI-результат).
        """
        # --- Уровень 0: детерминированные правила ---
        level0 = run_level0(
            Level0Input(
                resume_text=resume_text,
                is_blacklisted=is_blacklisted,
                is_duplicate=is_duplicate,
                hard_disqualify_reasons=hard_disqualify_reasons,
            )
        )

        if level0.rejected:
            result = ScreeningResult.create_level0_reject(
                tenant_id=tenant_id,
                application_id=application_id,
                candidate_id=candidate_id,
                vacancy_id=vacancy_id,
                level0=level0,
            )
            await self._repo.save(result)
            return Result.ok(result)

        # --- Уровень 1: AI-скоринг ---
        # 1. Получить вакансию и утверждённые критерии
        vacancy = await self._vacancy_repo.get(tenant_id, vacancy_id)
        if vacancy is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Вакансия не найдена",
                {"vacancy_id": str(vacancy_id)},
            )

        if vacancy.screening_criteria_provenance is None:
            return Result.err(
                ErrorCode.VALIDATION,
                "Критерии скрининга не сгенерированы для вакансии",
                {"vacancy_id": str(vacancy_id)},
            )

        criteria_provenance_id = vacancy.screening_criteria_provenance
        criteria_record = await self._provenance.get(tenant_id, criteria_provenance_id)
        if criteria_record is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Запись критериев не найдена в provenance",
                {"provenance_id": str(criteria_provenance_id)},
            )

        criteria_json = criteria_record.parsed_output

        # 2. Усечение резюме (бюджет токенов, JUGO-405)
        truncated_resume = resume_text[:MAX_RESUME_CHARS]

        # 3. AI-скоринг
        try:
            evaluations, summary, provenance_id, confidence, non_ai = await self._run_ai_scoring(
                tenant_id,
                criteria_json,
                truncated_resume,
                vacancy.role.title,
            )
        except Exception as exc:
            logger.error("AI screening failed, using non_ai fallback: %s", exc)
            evaluations, summary, provenance_id, confidence, non_ai = self._non_ai_fallback(
                criteria_json, str(exc)
            )

        # 4. Создать результат
        result = ScreeningResult.create_completed(
            tenant_id=tenant_id,
            application_id=application_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            evaluations=evaluations,
            criteria_provenance_id=criteria_provenance_id,
            provenance_id=provenance_id,
            summary=summary,
            confidence=confidence,
            non_ai=non_ai,
        )

        # 5. Сохранить
        await self._repo.save(result)
        return Result.ok(result)

    async def _run_ai_scoring(
        self,
        tenant_id: TenantId,
        criteria_json: str,
        resume_text: str,
        vacancy_title: str,
    ) -> tuple[list[CriterionEvaluation], str, Any, float | None, bool]:
        """Вызвать LLM для скоринга по каждому критерию.

        Возвращает: evaluations, summary, provenance_id, confidence, non_ai.
        """
        spec = get_prompt(SCREENING_SCORE_PROMPT_ID, SCREENING_SCORE_PROMPT_VERSION)

        variables = {
            "criteria": criteria_json,
            "resume": resume_text,
            "vacancy_title": vacancy_title,
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
            input_refs={"input_hash": input_hash},
            variables=variables,
        )

        from ats.modules.m1_screening.domain.scoring_output import ScreeningScoreOutput

        response = await self._gateway.structured(request, ScreeningScoreOutput)
        parsed: ScreeningScoreOutput = response.parsed

        evaluations = [
            CriterionEvaluation(
                criterion_name=ev.criterion_name,
                category=ev.category,
                score=ev.score,
                weight=ev.weight,
                evidence=ev.evidence,
                explanation=ev.explanation,
                must_have=ev.must_have,
            )
            for ev in parsed.evaluations
        ]

        return (
            evaluations,
            parsed.summary,
            response.provenance_id,
            response.confidence,
            False,
        )

    def _non_ai_fallback(
        self, criteria_json: str, error_msg: str
    ) -> tuple[list[CriterionEvaluation], str, Any, float | None, bool]:
        """Детерминированный fallback при сбое LLM (устойчивость).

        Все критерии получают score=0.5 (нейтрально), recommendation=BORDERLINE.
        Provenance_id=None (non_ai=True).
        """
        evaluations: list[CriterionEvaluation] = []
        try:
            criteria = json.loads(criteria_json)
            for group in criteria.get("groups", []):
                for crit in group.get("criteria", []):
                    evaluations.append(
                        CriterionEvaluation(
                            criterion_name=crit.get("name", ""),
                            category=group.get("category", ""),
                            score=0.5,
                            weight=float(crit.get("weight", 0)),
                            evidence="",
                            explanation="LLM unavailable — neutral fallback",
                            must_have=bool(crit.get("must_have", False)),
                        )
                    )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Non-AI fallback criteria parse failed: %s", exc)

        return (
            evaluations,
            f"AI unavailable ({error_msg}). Neutral fallback applied.",
            None,
            None,
            True,
        )
