"""API-слой recruitment: HTTP-эндпоинты вакансий.

JUGO-120: CRUD вакансий.
JUGO-121: версионируемые наборы критериев.
JUGO-122: REST + справочники (грейды, статусы, форматы работы, причины отказов).
JUGO-124: статусная машина (publish/hold/close/cancel).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.recruitment.application.create_vacancy import (
    CreateVacancyInput,
    CreateVacancyResult,
)
from ats.modules.recruitment.application.manage_requirement_sets import (
    CreateRequirementSetInput,
)
from ats.modules.recruitment.application.vacancy_crud import UpdateVacancyInput
from ats.modules.recruitment.domain.requirement_set import RequirementOrigin
from ats.modules.recruitment.domain.vacancy import (
    Seniority,
    Vacancy,
    VacancyStatus,
)
from ats.shared.ids import IdempotencyKey, TenantId, VacancyId
from ats.shared.result import is_error

router = APIRouter(prefix="/vacancies", tags=["vacancies"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

# JUGO-122: справочник форматов работы (ТЗ §8.1).
WORK_FORMATS = ["remote", "hybrid", "onsite"]

# JUGO-122: справочник причин закрытия/отказа.
REJECTION_REASONS = [
    "filled_internally",
    "no_budget",
    "reorganized",
    "no_suitable_candidates",
    "position_eliminated",
    "other",
]


# ---------------------------------------------------------------------------
# Pydantic-схемы: вакансии
# ---------------------------------------------------------------------------


class CreateVacancyRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seniority: Seniority
    team: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, description="Описание роли")
    requirements: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class UpdateVacancyRequest(BaseModel):
    """Patch-запрос на обновление вакансии."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    requirements: list[str] | None = None
    nice_to_have: list[str] | None = None
    team: str | None = Field(default=None, min_length=1, max_length=200)
    hiring_team: str | None = Field(default=None, min_length=1, max_length=200)


class ScreeningCriteriaResponse(BaseModel):
    provenance_id: str | None = None
    summary: str | None = None
    groups: list[dict] | None = None
    scoring_logic: str | None = None
    reasoning: str | None = None
    error: str | None = None


class VacancyResponse(BaseModel):
    id: UUID
    status: str
    title: str
    seniority: str
    team: str
    hiring_team: str
    description: str
    requirements: list[str]
    nice_to_have: list[str]
    hired_count: int
    created_at: str
    updated_at: str
    closed_at: str | None = None
    screening_criteria_provenance: str | None = None


class VacancyListResponse(BaseModel):
    items: list[VacancyResponse]
    total: int
    limit: int
    offset: int


class CreateVacancyResponse(BaseModel):
    vacancy_id: UUID
    status: str
    criteria: ScreeningCriteriaResponse


# ---------------------------------------------------------------------------
# Pydantic-схемы: наборы критериев
# ---------------------------------------------------------------------------


class CreateRequirementSetRequest(BaseModel):
    """Создать новую версию критериев скрининга."""

    criteria: dict = Field(description="Схема ScreeningCriteriaOutput (ТЗ §8.2)")
    origin: RequirementOrigin = RequirementOrigin.AI
    provenance_id: UUID | None = None
    created_by: UUID | None = None


class RequirementSetResponse(BaseModel):
    id: UUID
    vacancy_id: UUID
    version_number: int
    criteria: dict
    origin: str
    status: str
    provenance_id: str | None = None
    created_by: str | None = None
    created_at: str
    activated_at: str | None = None


class RequirementSetListResponse(BaseModel):
    items: list[RequirementSetResponse]
    total: int


# ---------------------------------------------------------------------------
# Pydantic-схемы: справочники
# ---------------------------------------------------------------------------


class VacancyReferencesResponse(BaseModel):
    """JUGO-122: справочники для UI конструктора вакансий."""

    seniorities: list[str]
    statuses: list[str]
    work_formats: list[str]
    rejection_reasons: list[str]


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _vacancy_to_response(vacancy: Vacancy) -> VacancyResponse:
    return VacancyResponse(
        id=vacancy.id.value,
        status=vacancy.status.value,
        title=vacancy.role.title,
        seniority=vacancy.role.seniority.value,
        team=vacancy.role.team,
        hiring_team=vacancy.hiring_team,
        description=vacancy.role.description,
        requirements=vacancy.role.requirements,
        nice_to_have=vacancy.role.nice_to_have,
        hired_count=vacancy.hired_count,
        created_at=vacancy.created_at.isoformat(),
        updated_at=vacancy.updated_at.isoformat(),
        closed_at=vacancy.closed_at.isoformat() if vacancy.closed_at else None,
        screening_criteria_provenance=(
            str(vacancy.screening_criteria_provenance)
            if vacancy.screening_criteria_provenance
            else None
        ),
    )


def _req_set_to_response(req_set) -> RequirementSetResponse:
    d = req_set.to_dict()
    return RequirementSetResponse(
        id=UUID(d["id"]),
        vacancy_id=UUID(d["vacancy_id"]),
        version_number=d["version_number"],
        criteria=d["criteria"],
        origin=d["origin"],
        status=d["status"],
        provenance_id=d["provenance_id"],
        created_by=d["created_by"],
        created_at=d["created_at"],
        activated_at=d["activated_at"],
    )


def _err_status(code: str) -> int:
    """Маппинг ErrorCode → HTTP status."""
    return {
        "not_found": status.HTTP_404_NOT_FOUND,
        "validation": status.HTTP_400_BAD_REQUEST,
        "ai_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    }.get(code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Эндпоинты: создание вакансии + AI-критерии
# ---------------------------------------------------------------------------


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
        raise HTTPException(status_code=_err_status(err.code.value), detail=err.message)

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


# ---------------------------------------------------------------------------
# Эндпоинты: справочники (JUGO-122)
# ---------------------------------------------------------------------------


@router.get(
    "/references",
    response_model=VacancyReferencesResponse,
    summary="Справочники: грейды, статусы, форматы работы, причины отказов",
)
async def get_references() -> VacancyReferencesResponse:
    return VacancyReferencesResponse(
        seniorities=[s.value for s in Seniority],
        statuses=[s.value for s in VacancyStatus],
        work_formats=WORK_FORMATS,
        rejection_reasons=REJECTION_REASONS,
    )


# ---------------------------------------------------------------------------
# Эндпоинты: список + получение вакансии
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=VacancyListResponse,
    summary="Список вакансий с пагинацией и фильтром по статусу",
)
async def list_vacancies(
    status_filter: VacancyStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> VacancyListResponse:
    container = get_container()
    result = await container.vacancy_crud.list(
        tenant_id=_DEFAULT_TENANT,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    if is_error(result):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.message,
        )
    vacancies = result.value
    return VacancyListResponse(
        items=[_vacancy_to_response(v) for v in vacancies],
        total=len(vacancies),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{vacancy_id}",
    response_model=VacancyResponse,
    summary="Получить вакансию по ID",
)
async def get_vacancy(vacancy_id: UUID) -> VacancyResponse:
    container = get_container()
    result = await container.vacancy_crud.get(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _vacancy_to_response(result.value)


# ---------------------------------------------------------------------------
# Эндпоинты: обновление вакансии
# ---------------------------------------------------------------------------


@router.patch(
    "/{vacancy_id}",
    response_model=VacancyResponse,
    summary="Обновить описание роли вакансии (patch-семантика)",
)
async def update_vacancy(
    vacancy_id: UUID,
    req: UpdateVacancyRequest,
) -> VacancyResponse:
    container = get_container()
    dto = UpdateVacancyInput(
        title=req.title,
        description=req.description,
        requirements=req.requirements,
        nice_to_have=req.nice_to_have,
        team=req.team,
        hiring_team=req.hiring_team,
    )
    result = await container.vacancy_crud.update(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
        dto=dto,
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _vacancy_to_response(result.value)


# ---------------------------------------------------------------------------
# Эндпоинты: статусная машина (JUGO-124)
# ---------------------------------------------------------------------------


@router.post(
    "/{vacancy_id}/publish",
    response_model=VacancyResponse,
    summary="Опубликовать вакансию (draft → open)",
)
async def publish_vacancy(vacancy_id: UUID) -> VacancyResponse:
    container = get_container()
    result = await container.vacancy_crud.publish(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _vacancy_to_response(result.value)


@router.post(
    "/{vacancy_id}/hold",
    response_model=VacancyResponse,
    summary="Заморозить вакансию (open → on_hold)",
)
async def hold_vacancy(vacancy_id: UUID) -> VacancyResponse:
    container = get_container()
    result = await container.vacancy_crud.put_on_hold(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _vacancy_to_response(result.value)


@router.post(
    "/{vacancy_id}/close",
    response_model=VacancyResponse,
    summary="Закрыть вакансию (open/on_hold → closed)",
)
async def close_vacancy(vacancy_id: UUID) -> VacancyResponse:
    container = get_container()
    result = await container.vacancy_crud.close(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _vacancy_to_response(result.value)


@router.post(
    "/{vacancy_id}/cancel",
    response_model=VacancyResponse,
    summary="Отменить вакансию (draft/open/on_hold → canceled)",
)
async def cancel_vacancy(vacancy_id: UUID) -> VacancyResponse:
    container = get_container()
    result = await container.vacancy_crud.cancel(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _vacancy_to_response(result.value)


# ---------------------------------------------------------------------------
# Эндпоинты: наборы критериев (JUGO-121)
# ---------------------------------------------------------------------------


@router.post(
    "/{vacancy_id}/requirements",
    response_model=RequirementSetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать новую версию критериев скрининга",
)
async def create_requirement_set(
    vacancy_id: UUID,
    req: CreateRequirementSetRequest,
) -> RequirementSetResponse:
    container = get_container()
    dto = CreateRequirementSetInput(
        vacancy_id=VacancyId(vacancy_id),
        criteria=req.criteria,
        origin=req.origin,
        provenance_id=req.provenance_id,
        created_by=req.created_by,
    )
    result = await container.requirement_set_use_case.create(
        tenant_id=_DEFAULT_TENANT,
        dto=dto,
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _req_set_to_response(result.value.requirement_set)


@router.post(
    "/{vacancy_id}/requirements/{set_id}/activate",
    response_model=RequirementSetResponse,
    summary="Активировать версию критериев (архивирует предыдущую активную)",
)
async def activate_requirement_set(
    vacancy_id: UUID,
    set_id: UUID,
) -> RequirementSetResponse:
    container = get_container()
    result = await container.requirement_set_use_case.activate(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
        set_id=set_id,
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )
    return _req_set_to_response(result.value)


@router.get(
    "/{vacancy_id}/requirements",
    response_model=RequirementSetListResponse,
    summary="Список всех версий критериев вакансии",
)
async def list_requirement_sets(vacancy_id: UUID) -> RequirementSetListResponse:
    container = get_container()
    result = await container.requirement_set_use_case.list_versions(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.message,
        )
    versions = result.value
    return RequirementSetListResponse(
        items=[_req_set_to_response(rs) for rs in versions],
        total=len(versions),
    )


@router.get(
    "/{vacancy_id}/requirements/active",
    response_model=RequirementSetResponse | None,
    summary="Получить активную версию критериев вакансии",
)
async def get_active_requirement_set(vacancy_id: UUID) -> RequirementSetResponse | None:
    container = get_container()
    result = await container.requirement_set_use_case.get_active(
        tenant_id=_DEFAULT_TENANT,
        vacancy_id=VacancyId(vacancy_id),
    )
    if is_error(result):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.message,
        )
    active = result.value
    if active is None:
        return None
    return _req_set_to_response(active)
