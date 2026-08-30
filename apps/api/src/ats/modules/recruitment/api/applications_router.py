"""API-слой recruitment: HTTP-эндпоинты заявок (pipeline кандидатов).

JUGO-141: создание, переход, отклонение, список, получение.
JUGO-143: треды комментариев с @упоминаниями и наблюдателями.
JUGO-144: агрегированный таймлайн заявки.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.recruitment.application.move_application import MoveApplicationInput
from ats.modules.recruitment.application.reject_application import RejectApplicationInput
from ats.modules.recruitment.domain.application import ApplicationOrigin, ApplicationStage
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, UserId, VacancyId
from ats.shared.result import is_error

router = APIRouter(prefix="/applications", tags=["applications"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic модели
# ---------------------------------------------------------------------------


class CreateApplicationRequest(BaseModel):
    candidate_id: UUID
    vacancy_id: UUID
    origin: ApplicationOrigin = ApplicationOrigin.INCOMING
    resume_id: UUID | None = None


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
    origin: str = "incoming"
    current_stage_id: UUID | None = None
    stage_entered_at: str | None = None
    score: float | None = None
    score_provenance: UUID | None = None
    screening_score: float | None = None
    risk_level: str = "none"
    rejection_reason_code: str | None = None
    rejection_reason_label: str | None = None
    resume_id: UUID | None = None
    transitions: list[StageTransitionResponse] = Field(default_factory=list)
    is_terminal: bool
    is_rejected: bool = False
    is_active: bool = True
    created_at: str
    updated_at: str


class MoveApplicationRequest(BaseModel):
    to_stage: ApplicationStage
    reason: str = ""
    ai_provenance: UUID | None = None


class RejectApplicationRequest(BaseModel):
    reason_code: str
    reason_label: str
    internal_note: str | None = None


class CreateThreadRequest(BaseModel):
    title: str = ""
    observers: list[str] = Field(default_factory=list)


class AddCommentRequest(BaseModel):
    author_id: UUID
    body: str
    is_private: bool = False
    attachments: list[str] = Field(default_factory=list)


class CommentResponse(BaseModel):
    id: UUID
    thread_id: UUID
    author_id: UUID
    body: str
    is_private: bool
    mentions: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CommentThreadResponse(BaseModel):
    id: UUID
    application_id: UUID
    title: str = ""
    observers: list[str] = Field(default_factory=list)
    comments: list[CommentResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str


class TimelineEntryResponse(BaseModel):
    event_type: str
    timestamp: str
    title: str
    description: str = ""
    actor: str = ""
    metadata: dict = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    application_id: UUID
    entries: list[TimelineEntryResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Маппинг
# ---------------------------------------------------------------------------


def _to_response(app) -> ApplicationResponse:
    return ApplicationResponse(
        id=app.id,
        candidate_id=app.candidate_id.value,
        vacancy_id=app.vacancy_id.value,
        stage=app.stage.value,
        origin=app.origin.value,
        current_stage_id=app.current_stage_id,
        stage_entered_at=app.stage_entered_at.isoformat() if app.stage_entered_at else None,
        score=app.score,
        score_provenance=app.score_provenance,
        screening_score=app.screening_score,
        risk_level=app.risk_level.value,
        rejection_reason_code=app.rejection_reason_code,
        rejection_reason_label=app.rejection_reason_label,
        resume_id=app.resume_id,
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
        is_rejected=app.is_rejected,
        is_active=app.is_active,
        created_at=app.created_at.isoformat(),
        updated_at=app.updated_at.isoformat(),
    )


def _thread_to_response(thread) -> CommentThreadResponse:
    return CommentThreadResponse(
        id=thread.id,
        application_id=thread.application_id,
        title=thread.title,
        observers=thread.observers,
        comments=[
            CommentResponse(
                id=c.id,
                thread_id=c.thread_id,
                author_id=c.author_id.value,
                body=c.body,
                is_private=c.is_private,
                mentions=c.mentions,
                attachments=c.attachments,
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
            for c in thread.comments
        ],
        created_at=thread.created_at.isoformat(),
        updated_at=thread.updated_at.isoformat(),
    )


def _timeline_to_response(timeline) -> TimelineResponse:
    return TimelineResponse(
        application_id=timeline.application_id,
        entries=[
            TimelineEntryResponse(
                event_type=e.event_type,
                timestamp=e.timestamp.isoformat(),
                title=e.title,
                description=e.description,
                actor=e.actor,
                metadata=e.metadata,
            )
            for e in timeline.sorted_entries
        ],
    )


_ERROR_CODE_MAP = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "conflict": status.HTTP_409_CONFLICT,
    "validation": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


def _raise_for_result(result) -> None:
    if is_error(result):
        code = _ERROR_CODE_MAP.get(result.error.code.value, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=code, detail=result.error.message)


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


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
        origin=req.origin,
        resume_id=req.resume_id,
    )
    if is_error(result):
        code = _ERROR_CODE_MAP.get(result.error.code.value, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=code, detail=result.error.message)
    return _to_response(result.value)


@router.get(
    "",
    response_model=list[ApplicationResponse],
    summary="Список заявок (с фильтром по вакансии)",
)
async def list_applications(
    vacancy_id: UUID | None = Query(None, description="Фильтр по вакансии"),
) -> list[ApplicationResponse]:
    container = get_container()
    if vacancy_id is not None:
        apps = await container.application_repository.list_by_vacancy(
            _DEFAULT_TENANT, VacancyId(vacancy_id)
        )
    else:
        apps = await container.application_repository.list_by_candidate(
            _DEFAULT_TENANT, CandidateId(UUID(int=0))
        )
        apps = []  # без фильтра возвращаем пустой список (безопасность)
    return [_to_response(a) for a in apps]


@router.get(
    "/{application_id}",
    response_model=ApplicationResponse,
    summary="Получить заявку по ID",
)
async def get_application(application_id: UUID) -> ApplicationResponse:
    container = get_container()
    app = await container.application_repository.get(_DEFAULT_TENANT, application_id)
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return _to_response(app)


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
    _raise_for_result(result)
    return _to_response(result.value)


@router.post(
    "/{application_id}/reject",
    response_model=ApplicationResponse,
    summary="Отклонить заявку с официальной причиной (JUGO-141)",
)
async def reject_application(
    application_id: UUID, req: RejectApplicationRequest
) -> ApplicationResponse:
    container = get_container()
    result = await container.reject_application.execute(
        tenant_id=_DEFAULT_TENANT,
        input_dto=RejectApplicationInput(
            application_id=application_id,
            reason_code=req.reason_code,
            reason_label=req.reason_label,
            internal_note=req.internal_note,
        ),
    )
    _raise_for_result(result)
    return _to_response(result.value)


@router.get(
    "/{application_id}/timeline",
    response_model=TimelineResponse,
    summary="Агрегированный таймлайн заявки (JUGO-144)",
)
async def get_timeline(application_id: UUID) -> TimelineResponse:
    container = get_container()
    result = await container.application_timeline.execute(
        tenant_id=_DEFAULT_TENANT,
        application_id=application_id,
    )
    _raise_for_result(result)
    return _timeline_to_response(result.value)


# ---------------------------------------------------------------------------
# Комментарии (JUGO-143)
# ---------------------------------------------------------------------------


@router.post(
    "/{application_id}/threads",
    response_model=CommentThreadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать тред комментариев на заявке (JUGO-143)",
)
async def create_thread(application_id: UUID, req: CreateThreadRequest) -> CommentThreadResponse:
    container = get_container()
    result = await container.comment_use_case.create_thread(
        tenant_id=_DEFAULT_TENANT,
        application_id=application_id,
        title=req.title,
        observers=req.observers,
    )
    _raise_for_result(result)
    return _thread_to_response(result.value)


@router.get(
    "/{application_id}/threads",
    response_model=list[CommentThreadResponse],
    summary="Список тредов комментариев заявки (JUGO-143)",
)
async def list_threads(application_id: UUID) -> list[CommentThreadResponse]:
    container = get_container()
    threads = await container.comment_use_case.list_threads(_DEFAULT_TENANT, application_id)
    return [_thread_to_response(t) for t in threads]


@router.post(
    "/{application_id}/threads/{thread_id}/comments",
    response_model=CommentThreadResponse,
    summary="Добавить комментарий в тред (JUGO-143)",
)
async def add_comment(
    application_id: UUID, thread_id: UUID, req: AddCommentRequest
) -> CommentThreadResponse:
    container = get_container()
    result = await container.comment_use_case.add_comment(
        tenant_id=_DEFAULT_TENANT,
        thread_id=thread_id,
        author_id=UserId(req.author_id),
        body=req.body,
        is_private=req.is_private,
        attachments=req.attachments,
    )
    _raise_for_result(result)
    return _thread_to_response(result.value)
