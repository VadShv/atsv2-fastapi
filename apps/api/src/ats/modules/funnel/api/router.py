"""API-слой funnel: пресеты воронки, переходы, решения НМ (JUGO-130..135).

JUGO-130: CRUD пресетов + стадии.
JUGO-131: снапшот пресета на вакансию.
JUGO-132: переход заявки между стадиями.
JUGO-134: решения НМ.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.funnel.application.funnel_use_cases import (
    AddStageInput,
    TransitionInput,
)
from ats.modules.funnel.domain.funnel import (
    CanonicalPhase,
    HMDecisionType,
)
from ats.shared.ids import TenantId
from ats.shared.result import Result, is_error

router = APIRouter(prefix="/funnel", tags=["funnel"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic-схемы: пресеты
# ---------------------------------------------------------------------------


class StageResponse(BaseModel):
    id: UUID
    canonical_phase: str
    name: str
    order_no: int
    category: str
    sla_hours: int | None = None
    substages: list[str] = Field(default_factory=list)
    is_terminal: bool


class FunnelPresetResponse(BaseModel):
    id: UUID
    name: str
    status: str
    stages: list[StageResponse]
    created_at: str
    updated_at: str


class FunnelPresetListResponse(BaseModel):
    items: list[FunnelPresetResponse]
    total: int


class CreatePresetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class AddStageRequest(BaseModel):
    canonical_phase: CanonicalPhase
    name: str = Field(min_length=1, max_length=100)
    sla_hours: int | None = None
    substages: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pydantic-схемы: переходы
# ---------------------------------------------------------------------------


class TransitionRequest(BaseModel):
    application_id: UUID
    vacancy_id: UUID
    from_stage_id: UUID | None = None
    to_stage_id: UUID
    candidate_id: UUID
    reason: str = ""
    actor_type: str = "user"
    ai_provenance: UUID | None = None


class TransitionResponse(BaseModel):
    id: UUID
    from_stage_id: str | None = None
    to_stage_id: str
    at: str
    reason: str
    actor_type: str
    ai_provenance: str | None = None


class TransitionListResponse(BaseModel):
    items: list[TransitionResponse]
    total: int


# ---------------------------------------------------------------------------
# Pydantic-схемы: решения НМ
# ---------------------------------------------------------------------------


class HMDecisionRequest(BaseModel):
    application_id: UUID
    stage_id: UUID
    decision: HMDecisionType
    justification: str = Field(min_length=1)
    created_by: UUID


class HMDecisionResponse(BaseModel):
    id: UUID
    application_id: UUID
    stage_id: UUID
    decision: str
    justification: str
    created_by: str
    created_at: str


class HMDecisionListResponse(BaseModel):
    items: list[HMDecisionResponse]
    total: int


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _err_status(code: str) -> int:
    return {
        "not_found": status.HTTP_404_NOT_FOUND,
        "validation": status.HTTP_400_BAD_REQUEST,
    }.get(code, status.HTTP_400_BAD_REQUEST)


def _raise_if_error(result: Result) -> None:
    """Raise HTTPException if the Result is an error."""
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value),
            detail=result.error.message,
        )


def _preset_to_response(preset) -> FunnelPresetResponse:
    return FunnelPresetResponse(
        id=preset.id,
        name=preset.name,
        status=preset.status.value,
        stages=[
            StageResponse(
                id=s.id,
                canonical_phase=s.canonical_phase.value,
                name=s.name,
                order_no=s.order_no,
                category=s.category.value,
                sla_hours=s.sla_hours,
                substages=s.substages,
                is_terminal=s.is_terminal,
            )
            for s in preset.stages
        ],
        created_at=preset.created_at.isoformat(),
        updated_at=preset.updated_at.isoformat(),
    )


def _transition_to_response(t) -> TransitionResponse:
    return TransitionResponse(
        id=t.id,
        from_stage_id=str(t.from_stage_id) if t.from_stage_id else None,
        to_stage_id=str(t.to_stage_id),
        at=t.at.isoformat(),
        reason=t.reason,
        actor_type=t.actor_type,
        ai_provenance=str(t.ai_provenance) if t.ai_provenance else None,
    )


def _decision_to_response(d) -> HMDecisionResponse:
    return HMDecisionResponse(
        id=d.id,
        application_id=d.application_id,
        stage_id=d.stage_id,
        decision=d.decision.value,
        justification=d.justification,
        created_by=str(d.created_by),
        created_at=d.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Эндпоинты: пресеты воронки (JUGO-130)
# ---------------------------------------------------------------------------


@router.post(
    "/presets",
    response_model=FunnelPresetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пресет воронки",
)
async def create_preset(req: CreatePresetRequest) -> FunnelPresetResponse:
    container = get_container()
    result = await container.funnel_preset_use_case.create_preset(
        tenant_id=_DEFAULT_TENANT,
        name=req.name,
    )
    _raise_if_error(result)
    return _preset_to_response(result.value)


@router.get(
    "/presets",
    response_model=FunnelPresetListResponse,
    summary="Список пресетов воронки",
)
async def list_presets(
    include_archived: bool = Query(default=False),
) -> FunnelPresetListResponse:
    container = get_container()
    result = await container.funnel_preset_use_case.list_presets(
        tenant_id=_DEFAULT_TENANT,
        include_archived=include_archived,
    )
    _raise_if_error(result)
    presets = result.value
    return FunnelPresetListResponse(
        items=[_preset_to_response(p) for p in presets],
        total=len(presets),
    )


@router.get(
    "/presets/{preset_id}",
    response_model=FunnelPresetResponse,
    summary="Получить пресет по ID",
)
async def get_preset(preset_id: UUID) -> FunnelPresetResponse:
    container = get_container()
    result = await container.funnel_preset_use_case.get_preset(
        tenant_id=_DEFAULT_TENANT,
        preset_id=preset_id,
    )
    _raise_if_error(result)
    return _preset_to_response(result.value)


@router.post(
    "/presets/{preset_id}/stages",
    response_model=FunnelPresetResponse,
    summary="Добавить стадию в пресет",
)
async def add_stage(preset_id: UUID, req: AddStageRequest) -> FunnelPresetResponse:
    container = get_container()
    result = await container.funnel_preset_use_case.add_stage(
        tenant_id=_DEFAULT_TENANT,
        preset_id=preset_id,
        dto=AddStageInput(
            canonical_phase=req.canonical_phase,
            name=req.name,
            sla_hours=req.sla_hours,
        ),
    )
    _raise_if_error(result)
    return _preset_to_response(result.value)


@router.post(
    "/presets/{preset_id}/publish",
    response_model=FunnelPresetResponse,
    summary="Опубликовать пресет воронки",
)
async def publish_preset(preset_id: UUID) -> FunnelPresetResponse:
    container = get_container()
    result = await container.funnel_preset_use_case.publish_preset(
        tenant_id=_DEFAULT_TENANT,
        preset_id=preset_id,
    )
    _raise_if_error(result)
    return _preset_to_response(result.value)


@router.post(
    "/presets/{preset_id}/archive",
    response_model=FunnelPresetResponse,
    summary="Архивировать пресет воронки",
)
async def archive_preset(preset_id: UUID) -> FunnelPresetResponse:
    container = get_container()
    result = await container.funnel_preset_use_case.archive_preset(
        tenant_id=_DEFAULT_TENANT,
        preset_id=preset_id,
    )
    _raise_if_error(result)
    return _preset_to_response(result.value)


# ---------------------------------------------------------------------------
# Эндпоинты: снапшот (JUGO-131)
# ---------------------------------------------------------------------------


@router.post(
    "/presets/{preset_id}/snapshot/{vacancy_id}",
    summary="Создать снапшот пресета для вакансии",
    status_code=status.HTTP_201_CREATED,
)
async def snapshot_for_vacancy(preset_id: UUID, vacancy_id: UUID) -> dict:
    container = get_container()
    result = await container.funnel_preset_use_case.snapshot_for_vacancy(
        tenant_id=_DEFAULT_TENANT,
        preset_id=preset_id,
        vacancy_id=vacancy_id,
    )
    _raise_if_error(result)
    snapshot = result.value
    return {
        "vacancy_id": str(snapshot.vacancy_id),
        "preset_id": str(snapshot.preset_id),
        "stages_count": len(snapshot.stages),
    }


# ---------------------------------------------------------------------------
# Эндпоинты: переходы (JUGO-132)
# ---------------------------------------------------------------------------


@router.post(
    "/transitions",
    response_model=TransitionResponse,
    summary="Перевести заявку на новую стадию (единая точка смены этапа)",
)
async def transition(req: TransitionRequest) -> TransitionResponse:
    container = get_container()
    result = await container.funnel_transition_use_case.transition(
        tenant_id=_DEFAULT_TENANT,
        dto=TransitionInput(
            application_id=req.application_id,
            vacancy_id=req.vacancy_id,
            from_stage_id=req.from_stage_id,
            to_stage_id=req.to_stage_id,
            candidate_id=req.candidate_id,
            reason=req.reason,
            actor_type=req.actor_type,
            ai_provenance=req.ai_provenance,
        ),
    )
    _raise_if_error(result)
    return _transition_to_response(result.value)


@router.get(
    "/transitions/{application_id}",
    response_model=TransitionListResponse,
    summary="История переходов заявки",
)
async def list_transitions(application_id: UUID) -> TransitionListResponse:
    container = get_container()
    result = await container.funnel_transition_use_case.get_transitions(
        tenant_id=_DEFAULT_TENANT,
        application_id=application_id,
    )
    _raise_if_error(result)
    transitions = result.value
    return TransitionListResponse(
        items=[_transition_to_response(t) for t in transitions],
        total=len(transitions),
    )


# ---------------------------------------------------------------------------
# Эндпоинты: решения НМ (JUGO-134)
# ---------------------------------------------------------------------------


@router.post(
    "/hm-decisions",
    response_model=HMDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Записать решение нанимающего менеджера",
)
async def record_hm_decision(req: HMDecisionRequest) -> HMDecisionResponse:
    container = get_container()
    result = await container.hm_decision_use_case.record_decision(
        tenant_id=_DEFAULT_TENANT,
        application_id=req.application_id,
        stage_id=req.stage_id,
        decision=req.decision,
        justification=req.justification,
        created_by=req.created_by,
    )
    _raise_if_error(result)
    return _decision_to_response(result.value)


@router.get(
    "/hm-decisions/{application_id}",
    response_model=HMDecisionListResponse,
    summary="Список решений НМ по заявке",
)
async def list_hm_decisions(application_id: UUID) -> HMDecisionListResponse:
    container = get_container()
    result = await container.hm_decision_use_case.list_decisions(
        tenant_id=_DEFAULT_TENANT,
        application_id=application_id,
    )
    _raise_if_error(result)
    decisions = result.value
    return HMDecisionListResponse(
        items=[_decision_to_response(d) for d in decisions],
        total=len(decisions),
    )
