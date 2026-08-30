"""M1 Screening — API: скрининг кандидатов (E-40).

Эндпоинты:
- POST /screening/run               — запустить скрининг для заявки
- GET  /screening/{screening_id}    — получить результат скрининга
- GET  /screening/by-application/{application_id} — результат по заявке
- GET  /screening/vacancy/{vacancy_id} — список результатов для вакансии
- GET  /screening/vacancy/{vacancy_id}/stale — устаревшие результаты
- POST /screening/{screening_id}/override — подтвердить/оспорить (JUGO-407)
- POST /screening/{screening_id}/invalidate — пометить устаревшим (JUGO-408)
- POST /vacancies/{vacancy_id}/screening/requirements:generate — драфт критериев (JUGO-401)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.m1_screening.domain.screening import (
    OverrideAction,
)
from ats.shared.ids import ApplicationId, CandidateId, TenantId, VacancyId
from ats.shared.result import is_error

router = APIRouter(prefix="/screening", tags=["screening"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------


class RunScreeningRequest(BaseModel):
    """Запрос на запуск скрининга."""

    application_id: UUID
    candidate_id: UUID
    vacancy_id: UUID
    resume_text: str = Field(min_length=1, description="Текст резюме кандидата")
    is_blacklisted: bool = False
    is_duplicate: bool = False
    hard_disqualify_reasons: list[str] = Field(default_factory=list)


class CriterionEvaluationResponse(BaseModel):
    criterion_name: str
    category: str
    score: float
    weight: float
    evidence: str = ""
    explanation: str = ""
    must_have: bool = False


class Level0ResultResponse(BaseModel):
    rejected: bool
    reason: str = ""
    matched_rules: list[str] = Field(default_factory=list)


class ScreeningResponse(BaseModel):
    """Результат скрининга (whitebox: все оценки и reasoning доступны)."""

    id: str
    application_id: str
    candidate_id: str
    vacancy_id: str
    status: str
    total_score: float
    recommendation: str
    confidence: float | None = None
    evaluations: list[CriterionEvaluationResponse] = Field(default_factory=list)
    level0: Level0ResultResponse | None = None
    provenance_id: str | None = None
    criteria_provenance_id: str | None = None
    summary: str = ""
    non_ai: bool = False
    overridden_by: str = ""
    override_action: str | None = None
    is_stale: bool = False
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None


class ScreeningListResponse(BaseModel):
    results: list[ScreeningResponse]
    total: int


class OverrideRequest(BaseModel):
    action: str = Field(description="confirm или dispute")
    user_id: str = Field(description="ID пользователя")


class GenerateCriteriaRequest(BaseModel):
    """JUGO-401: запрос генерации драфта критериев."""

    pass  # использует role из вакансии


class GenerateCriteriaResponse(BaseModel):
    vacancy_id: str
    criteria_provenance_id: str
    criteria: Any
    error: str | None = None


# ---------------------------------------------------------------------------
# Маппинг домен → response
# ---------------------------------------------------------------------------


def _to_response(result: Any) -> ScreeningResponse:
    level0_resp = None
    if result.level0 is not None:
        level0_resp = Level0ResultResponse(
            rejected=result.level0.rejected,
            reason=result.level0.reason,
            matched_rules=result.level0.matched_rules,
        )
    return ScreeningResponse(
        id=str(result.id.value),
        application_id=str(result.application_id.value),
        candidate_id=str(result.candidate_id.value),
        vacancy_id=str(result.vacancy_id.value),
        status=result.status.value,
        total_score=result.total_score,
        recommendation=result.recommendation.value,
        confidence=result.confidence,
        evaluations=[
            CriterionEvaluationResponse(
                criterion_name=ev.criterion_name,
                category=ev.category,
                score=ev.score,
                weight=ev.weight,
                evidence=ev.evidence,
                explanation=ev.explanation,
                must_have=ev.must_have,
            )
            for ev in result.evaluations
        ],
        level0=level0_resp,
        provenance_id=str(result.provenance_id.value) if result.provenance_id else None,
        criteria_provenance_id=(
            str(result.criteria_provenance_id.value) if result.criteria_provenance_id else None
        ),
        summary=result.summary,
        non_ai=result.non_ai,
        overridden_by=result.overridden_by,
        override_action=result.override_action.value if result.override_action else None,
        is_stale=result.is_stale,
        created_at=result.created_at.isoformat(),
        updated_at=result.updated_at.isoformat(),
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
    )


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=ScreeningResponse,
    summary="Запустить скрининг кандидата",
)
async def run_screening(body: RunScreeningRequest) -> ScreeningResponse:
    container = get_container()
    result = await container.screen_candidate_use_case.execute(
        tenant_id=_DEFAULT_TENANT,
        application_id=ApplicationId(body.application_id),
        candidate_id=CandidateId(body.candidate_id),
        vacancy_id=VacancyId(body.vacancy_id),
        resume_text=body.resume_text,
        is_blacklisted=body.is_blacklisted,
        is_duplicate=body.is_duplicate,
        hard_disqualify_reasons=body.hard_disqualify_reasons or None,
    )
    if is_error(result):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.message,
        )
    return _to_response(result.value)


@router.get(
    "/{screening_id}",
    response_model=ScreeningResponse,
    summary="Получить результат скрининга по ID",
)
async def get_screening(screening_id: UUID) -> ScreeningResponse:
    container = get_container()
    result = await container.screening_result_repository.get(_DEFAULT_TENANT, screening_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Результат скрининга не найден",
        )
    return _to_response(result)


@router.get(
    "/by-application/{application_id}",
    response_model=ScreeningResponse,
    summary="Получить результат скрининга по заявке",
)
async def get_screening_by_application(application_id: UUID) -> ScreeningResponse:
    container = get_container()
    result = await container.screening_result_repository.get_by_application(
        _DEFAULT_TENANT, ApplicationId(application_id)
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Скрининг для заявки не найден",
        )
    return _to_response(result)


@router.get(
    "/vacancy/{vacancy_id}",
    response_model=ScreeningListResponse,
    summary="Список результатов скрининга для вакансии",
)
async def list_screening_by_vacancy(
    vacancy_id: UUID, limit: int = 50, offset: int = 0
) -> ScreeningListResponse:
    container = get_container()
    items = await container.screening_result_repository.list_by_vacancy(
        _DEFAULT_TENANT, vacancy_id, limit=limit, offset=offset
    )
    return ScreeningListResponse(results=[_to_response(r) for r in items], total=len(items))


@router.get(
    "/vacancy/{vacancy_id}/stale",
    response_model=ScreeningListResponse,
    summary="Устаревшие результаты скрининга (is_stale=True)",
)
async def list_stale_screening(vacancy_id: UUID) -> ScreeningListResponse:
    container = get_container()
    items = await container.screening_result_repository.list_stale(_DEFAULT_TENANT, vacancy_id)
    return ScreeningListResponse(results=[_to_response(r) for r in items], total=len(items))


@router.post(
    "/{screening_id}/override",
    response_model=ScreeningResponse,
    summary="Подтвердить/оспорить результат скрининга (JUGO-407)",
)
async def override_screening(screening_id: UUID, body: OverrideRequest) -> ScreeningResponse:
    container = get_container()
    result = await container.screening_result_repository.get(_DEFAULT_TENANT, screening_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Результат скрининга не найден",
        )
    try:
        action = OverrideAction(body.action)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Недопустимое действие: {body.action}",
        ) from None

    result.override(action, body.user_id)
    await container.screening_result_repository.save(result)
    return _to_response(result)


@router.post(
    "/{screening_id}/invalidate",
    response_model=ScreeningResponse,
    summary="Пометить результат устаревшим (JUGO-408)",
)
async def invalidate_screening(screening_id: UUID) -> ScreeningResponse:
    container = get_container()
    result = await container.screening_result_repository.get(_DEFAULT_TENANT, screening_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Результат скрининга не найден",
        )
    result.mark_stale()
    await container.screening_result_repository.save(result)
    return _to_response(result)
