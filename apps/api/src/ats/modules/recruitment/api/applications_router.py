"""API-слой recruitment: HTTP-эндпоинты заявок (pipeline кандидатов)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.recruitment.application.move_application import MoveApplicationInput
from ats.modules.recruitment.domain.application import ApplicationStage
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, VacancyId
from ats.shared.result import is_error

router = APIRouter(prefix="/applications", tags=["applications"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


class CreateApplicationRequest(BaseModel):
    candidate_id: UUID
    vacancy_id: UUID


class StageTransitionResponse(BaseModel):
    from_stage: str
    to_stage: str
    at: str
    reason: str = ""
    ai_provenance: UUID | None = None


class ApplicationResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    vacancy_id: UUID
    stage: str
    score: float | None = None
    score_provenance: UUID | None = None
    transitions: list[StageTransitionResponse] = Field(default_factory=list)
    is_terminal: bool


class MoveApplicationRequest(BaseModel):
    to_stage: ApplicationStage
    reason: str = ""
    ai_provenance: UUID | None = None


def _to_response(app) -> ApplicationResponse:
    return ApplicationResponse(
        id=app.id,
        candidate_id=app.candidate_id.value,
        vacancy_id=app.vacancy_id.value,
        stage=app.stage.value,
        score=app.score,
        score_provenance=app.score_provenance,
        transitions=[
            StageTransitionResponse(
                from_stage=t.from_stage.value,
                to_stage=t.to_stage.value,
                at=t.at.isoformat(),
                reason=t.reason,
                ai_provenance=t.ai_provenance,
            )
            for t in app.transitions
        ],
        is_terminal=app.is_terminal,
    )


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать заявку: привязать кандидата к вакансии",
)
async def create_application(req: CreateApplicationRequest) -> ApplicationResponse:
    container = get_container()
    result = await container.create_application.execute(
        tenant_id=_DEFAULT_TENANT,
        candidate_id=CandidateId(req.candidate_id),
        vacancy_id=VacancyId(req.vacancy_id),
        idempotency_key=IdempotencyKey(f"app-{req.candidate_id}-{req.vacancy_id}"),
    )
    if is_error(result):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.message
        )
    return _to_response(result.value)


@router.post(
    "/{application_id}/move",
    response_model=ApplicationResponse,
    summary="Перевести заявку на следующую стадию пайплайна",
)
async def move_application(
    application_id: UUID, req: MoveApplicationRequest
) -> ApplicationResponse:
    container = get_container()
    result = await container.move_application.execute(
        tenant_id=_DEFAULT_TENANT,
        input_dto=MoveApplicationInput(
            application_id=application_id,
            to_stage=req.to_stage,
            reason=req.reason,
            ai_provenance=req.ai_provenance,
        ),
    )
    if is_error(result):
        code_map = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "conflict": status.HTTP_409_CONFLICT,
        }
        raise HTTPException(
            status_code=code_map.get(
                result.error.code.value, status.HTTP_400_BAD_REQUEST
            ),
            detail=result.error.message,
        )
    return _to_response(result.value)
