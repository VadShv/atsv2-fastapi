"""API-слой recruitment: HTTP-эндпоинты вакансий."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.recruitment.application.create_vacancy import (
    CreateVacancyInput,
    CreateVacancyResult,
)
from ats.modules.recruitment.domain.vacancy import Seniority
from ats.shared.ids import IdempotencyKey, TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/vacancies", tags=["vacancies"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


class CreateVacancyRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seniority: Seniority
    team: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, description="Описание роли")
    requirements: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class ScreeningCriteriaResponse(BaseModel):
    provenance_id: str | None = None
    summary: str | None = None
    groups: list[dict] | None = None
    scoring_logic: str | None = None
    reasoning: str | None = None
    error: str | None = None


class CreateVacancyResponse(BaseModel):
    vacancy_id: UUID
    status: str
    criteria: ScreeningCriteriaResponse


@router.post(
    "",
    response_model=CreateVacancyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать вакансию и сгенерировать AI-критерии скрининга",
)
async def create_vacancy(req: CreateVacancyRequest) -> CreateVacancyResponse:
    container = get_container()

    input_dto = CreateVacancyInput(
        title=req.title,
        seniority=req.seniority,
        team=req.team,
        description=req.description,
        requirements=req.requirements,
        nice_to_have=req.nice_to_have,
    )

    idem_key = IdempotencyKey(f"create-vacancy-{req.title}-{req.seniority.value}")

    result = await container.create_vacancy.execute(
        tenant_id=_DEFAULT_TENANT,
        input_dto=input_dto,
        idempotency_key=idem_key,
    )

    if is_error(result):
        err = result.error
        code_map = {
            "validation": status.HTTP_400_BAD_REQUEST,
            "ai_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
        }
        raise HTTPException(
            status_code=code_map.get(err.code.value, status.HTTP_400_BAD_REQUEST),
            detail=err.message,
        )

    res: CreateVacancyResult = result.value

    criteria_resp = ScreeningCriteriaResponse(
        provenance_id=res.criteria_provenance_id,
        error=res.criteria_error,
    )
    if res.criteria is not None:
        c = res.criteria  # ScreeningCriteriaOutput
        criteria_resp.summary = c.summary
        criteria_resp.groups = [g.model_dump() for g in c.groups]
        criteria_resp.scoring_logic = c.scoring_logic
        criteria_resp.reasoning = c.reasoning

    return CreateVacancyResponse(
        vacancy_id=res.vacancy_id.value,
        status="draft",
        criteria=criteria_resp,
    )
