"""API-слой ai_core: AI Skills — прямые вызовы скиллов и регенерация.

E-32: AI Skills API. Скиллы — это use cases поверх AIGateway.
Каждый вызов записывает provenance (whitebox), доступен через /ai/provenance/{id}.

Эндпоинты:
- GET  /skills                    — список доступных скиллов
- POST /skills/{skill_id}/run     — прямой запуск скилла с переменными
- POST /vacancies/{vacancy_id}/regenerate-criteria — регенерация критериев для вакансии
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.ai_core.domain.models import ProvenanceRecord
from ats.modules.recruitment.domain.vacancy import RoleDescription, Seniority
from ats.shared.ids import TenantId, VacancyId
from ats.shared.result import is_error

router = APIRouter(prefix="/skills", tags=["skills"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

# Реестр метаданных скиллов (id → описание, ожидаемые переменные)
_SKILL_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "generate_screening_criteria",
        "name": "Generate Screening Criteria",
        "description": (
            "Генерирует взвешенные критерии скрининга из описания роли вакансии. "
            "Возвращает ScreeningCriteriaOutput с группами, весами и логикой скоринга."
        ),
        "prompt_id": "screening_criteria",
        "prompt_version": "1.0.0",
        "output_schema": "ScreeningCriteriaOutput",
        "variables": ["role_description", "vacancy_title", "seniority", "team"],
    },
    {
        "id": "parse_resume",
        "name": "Parse Resume",
        "description": (
            "Извлекает структурированный профиль кандидата из сырого текста резюме. "
            "Возвращает ParsedResume с навыками, опытом, образованием."
        ),
        "prompt_id": "parse_resume",
        "prompt_version": "1.0.0",
        "output_schema": "ParsedResume",
        "variables": ["resume_text"],
    },
]


def _skill_meta(skill_id: str) -> dict[str, Any] | None:
    return next((s for s in _SKILL_REGISTRY if s["id"] == skill_id), None)


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------


class SkillSummaryResponse(BaseModel):
    """Краткое описание доступного скилла."""

    id: str
    name: str
    description: str
    prompt_id: str
    prompt_version: str
    output_schema: str
    variables: list[str]


class SkillListResponse(BaseModel):
    """Список доступных AI-скиллов."""

    skills: list[SkillSummaryResponse]
    total: int


class RunSkillRequest(BaseModel):
    """Запрос на запуск скилла с переменными."""

    variables: dict[str, str] = Field(description="Переменные для рендера промпта скилла")


class RunSkillResponse(BaseModel):
    """Результат запуска скилла: parsed output + provenance (whitebox)."""

    skill_id: str
    model: str
    parsed_output: Any = Field(description="Структурированный результат скилла")
    provenance_id: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    repaired: bool = False
    error: str | None = None


class RegenerateCriteriaResponse(BaseModel):
    """Результат регенерации критериев для вакансии."""

    vacancy_id: str
    criteria_provenance_id: str | None = None
    criteria: Any | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=SkillListResponse,
    summary="Список доступных AI-скиллов",
)
async def list_skills() -> SkillListResponse:
    skills = [
        SkillSummaryResponse(
            id=s["id"],
            name=s["name"],
            description=s["description"],
            prompt_id=s["prompt_id"],
            prompt_version=s["prompt_version"],
            output_schema=s["output_schema"],
            variables=s["variables"],
        )
        for s in _SKILL_REGISTRY
    ]
    return SkillListResponse(skills=skills, total=len(skills))


@router.post(
    "/{skill_id}/run",
    response_model=RunSkillResponse,
    summary="Прямой запуск AI-скилла с переменными",
)
async def run_skill(skill_id: str, body: RunSkillRequest) -> RunSkillResponse:
    meta = _skill_meta(skill_id)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Скилл не найден: {skill_id}",
        )

    container = get_container()
    gateway = container.ai_gateway

    if skill_id == "generate_screening_criteria":
        from ats.modules.ai_core.skills.generate_screening_criteria import (
            GenerateScreeningCriteria,
        )

        skill = GenerateScreeningCriteria(gateway)
        try:
            seniority = Seniority(body.variables.get("seniority", "middle"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Недопустимый seniority: {body.variables.get('seniority')}",
            ) from None
        role = RoleDescription(
            title=body.variables.get("vacancy_title", ""),
            seniority=seniority,
            team=body.variables.get("team", ""),
            description=body.variables.get("role_description", ""),
        )
        result = await skill.execute(_DEFAULT_TENANT, role)

    elif skill_id == "parse_resume":
        from ats.modules.ai_core.skills.parse_resume import ParseResume

        skill = ParseResume(gateway)
        result = await skill.execute(_DEFAULT_TENANT, body.variables.get("resume_text", ""))

    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Скилл не найден: {skill_id}",
        )

    if is_error(result):
        return RunSkillResponse(
            skill_id=skill_id,
            model="",
            parsed_output=None,
            provenance_id="",
            latency_ms=0,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            error=result.error.message,
        )

    parsed, provenance_id = result.value
    # Получаем метаданные из provenance (model, tokens, etc.)
    record: ProvenanceRecord | None = await container.provenance_ledger.get(
        _DEFAULT_TENANT, provenance_id
    )
    if record is not None:
        return RunSkillResponse(
            skill_id=skill_id,
            model=record.model,
            parsed_output=parsed.model_dump(mode="json"),
            provenance_id=str(provenance_id.value),
            latency_ms=record.latency_ms,
            tokens_in=record.tokens_in,
            tokens_out=record.tokens_out,
            cost_usd=record.cost_usd,
            error=None,
        )

    # Fallback: provenance не записан (не должно случаться)
    return RunSkillResponse(
        skill_id=skill_id,
        model="",
        parsed_output=parsed.model_dump(mode="json"),
        provenance_id=str(provenance_id.value),
        latency_ms=0,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
    )


# ---------------------------------------------------------------------------
# Регенерация критериев для существующей вакансии
# ---------------------------------------------------------------------------


@router.post(
    "/vacancies/{vacancy_id}/regenerate-criteria",
    response_model=RegenerateCriteriaResponse,
    summary="Регенерировать AI-критерии скрининга для существующей вакансии",
)
async def regenerate_criteria(vacancy_id: UUID) -> RegenerateCriteriaResponse:
    container = get_container()

    # 1. Получить вакансию
    vacancy_result = await container.vacancy_crud.get(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(vacancy_result):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=vacancy_result.error.message,
        )
    vacancy = vacancy_result.value

    # 2. Запустить скилл генерации критериев
    from ats.modules.ai_core.skills.generate_screening_criteria import (
        GenerateScreeningCriteria,
    )

    skill = GenerateScreeningCriteria(container.ai_gateway)
    result = await skill.execute(_DEFAULT_TENANT, vacancy.role)

    if is_error(result):
        return RegenerateCriteriaResponse(
            vacancy_id=str(vacancy_id),
            error=result.error.message,
        )

    parsed, provenance_id = result.value

    # 3. Привязать новый provenance к вакансии
    vacancy.attach_screening_criteria(provenance_id)
    await container.vacancy_repository.save(vacancy)

    return RegenerateCriteriaResponse(
        vacancy_id=str(vacancy_id),
        criteria_provenance_id=str(provenance_id.value),
        criteria=parsed.model_dump(mode="json"),
    )
