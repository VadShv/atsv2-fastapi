"""API-слой candidates: CRUD + факты + теги + blacklist + загрузка резюме + импорт."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile, status

from ats.infra.container_helpers import get_container
from ats.modules.candidates.api.schemas import (
    AddBlacklistRequest,
    AddFactRequest,
    AddTagRequest,
    BlacklistResponse,
    BulkImportRequest,
    BulkImportResultResponse,
    CandidateListResponse,
    CandidateResponse,
    CreateCandidateRequest,
    FactListResponse,
    FactResponse,
    TagListResponse,
    TagResponse,
    UpdateCandidateRequest,
)
from ats.modules.candidates.application.candidate_crud import (
    AddBlacklistInput,
    AddFactInput,
    AddTagInput,
    BulkImportRow,
    CreateCandidateInput,
    UpdateCandidateInput,
)
from ats.modules.candidates.domain.candidate import CandidateSource
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, UserId
from ats.shared.result import is_error

router = APIRouter(prefix="/candidates", tags=["candidates"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}


def _to_response(candidate) -> CandidateResponse:
    return CandidateResponse(
        id=candidate.id.value,
        full_name=candidate.full_name,
        headline=candidate.headline,
        skills=list(candidate.skills),
        location=candidate.location,
        source=candidate.source.value,
        pii_token=candidate.pii_token,
        resume_provenance=candidate.resume_provenance,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _fact_to_response(fact) -> FactResponse:
    return FactResponse(
        id=fact.id.value,
        fact_type=fact.fact_type.value,
        source=fact.source.value,
        content=fact.content,
        pinned=fact.pinned,
        confidence=fact.confidence,
        source_ref=fact.source_ref,
    )


def _tag_to_response(tag) -> TagResponse:
    return TagResponse(
        id=tag.id.value,
        name=tag.name,
        color=tag.color,
        created_by=tag.created_by.value if tag.created_by else None,
    )


def _err_status(code: str) -> int:
    mapping = {
        "validation": status.HTTP_400_BAD_REQUEST,
        "not_found": status.HTTP_404_NOT_FOUND,
        "conflict": status.HTTP_409_CONFLICT,
        "forbidden": status.HTTP_403_FORBIDDEN,
    }
    return mapping.get(code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CandidateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать кандидата вручную",
)
async def create_candidate(req: CreateCandidateRequest) -> CandidateResponse:
    container = get_container()
    dto = CreateCandidateInput(
        full_name=req.full_name,
        source=req.source,
        headline=req.headline,
        skills=req.skills,
        location=req.location,
        pii_token=req.pii_token,
    )
    result = await container.candidate_crud.create(_DEFAULT_TENANT, dto)
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return _to_response(result.value)


@router.get(
    "",
    response_model=CandidateListResponse,
    summary="Список кандидатов с пагинацией",
)
async def list_candidates(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CandidateListResponse:
    container = get_container()
    result = await container.candidate_crud.list(_DEFAULT_TENANT, limit, offset)
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    items = result.value
    return CandidateListResponse(
        items=[_to_response(c) for c in items],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{candidate_id}",
    response_model=CandidateResponse,
    summary="Получить кандидата по id",
)
async def get_candidate(candidate_id: UUID) -> CandidateResponse:
    container = get_container()
    result = await container.candidate_crud.get(_DEFAULT_TENANT, CandidateId(candidate_id))
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return _to_response(result.value)


@router.patch(
    "/{candidate_id}",
    response_model=CandidateResponse,
    summary="Обновить поля кандидата (patch)",
)
async def update_candidate(candidate_id: UUID, req: UpdateCandidateRequest) -> CandidateResponse:
    container = get_container()
    dto = UpdateCandidateInput(
        full_name=req.full_name,
        headline=req.headline,
        skills=req.skills,
        location=req.location,
    )
    result = await container.candidate_crud.update(_DEFAULT_TENANT, CandidateId(candidate_id), dto)
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return _to_response(result.value)


@router.delete(
    "/{candidate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить кандидата",
)
async def delete_candidate(candidate_id: UUID) -> None:
    container = get_container()
    result = await container.candidate_crud.delete(_DEFAULT_TENANT, CandidateId(candidate_id))
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


@router.post(
    "/{candidate_id}/facts",
    response_model=FactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить факт профиля кандидату",
)
async def add_fact(candidate_id: UUID, req: AddFactRequest) -> FactResponse:
    container = get_container()
    dto = AddFactInput(
        fact_type=req.fact_type,
        source=req.source,
        content=req.content,
        pinned=req.pinned,
        confidence=req.confidence,
        source_ref=req.source_ref,
    )
    result = await container.candidate_crud.add_fact(
        _DEFAULT_TENANT, CandidateId(candidate_id), dto
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return _fact_to_response(result.value)


@router.get(
    "/{candidate_id}/facts",
    response_model=FactListResponse,
    summary="Список фактов кандидата",
)
async def list_facts(candidate_id: UUID) -> FactListResponse:
    container = get_container()
    result = await container.candidate_crud.list_facts(_DEFAULT_TENANT, CandidateId(candidate_id))
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return FactListResponse(items=[_fact_to_response(f) for f in result.value])


@router.delete(
    "/{candidate_id}/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить факт кандидата",
)
async def delete_fact(candidate_id: UUID, fact_id: UUID) -> None:
    container = get_container()
    result = await container.candidate_crud.delete_fact(
        _DEFAULT_TENANT, CandidateId(candidate_id), str(fact_id)
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@router.post(
    "/{candidate_id}/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить тег кандидату",
)
async def add_tag(candidate_id: UUID, req: AddTagRequest) -> TagResponse:
    container = get_container()
    dto = AddTagInput(name=req.name, color=req.color)
    result = await container.candidate_crud.add_tag(_DEFAULT_TENANT, CandidateId(candidate_id), dto)
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return _tag_to_response(result.value)


@router.get(
    "/{candidate_id}/tags",
    response_model=TagListResponse,
    summary="Список тегов кандидата",
)
async def list_tags(candidate_id: UUID) -> TagListResponse:
    container = get_container()
    result = await container.candidate_crud.list_tags(_DEFAULT_TENANT, CandidateId(candidate_id))
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    return TagListResponse(items=[_tag_to_response(t) for t in result.value])


@router.delete(
    "/{candidate_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить тег кандидата",
)
async def remove_tag(candidate_id: UUID, tag_id: UUID) -> None:
    container = get_container()
    result = await container.candidate_crud.remove_tag(
        _DEFAULT_TENANT, CandidateId(candidate_id), str(tag_id)
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------


@router.post(
    "/{candidate_id}/blacklist",
    response_model=BlacklistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить кандидата в blacklist",
)
async def add_to_blacklist(candidate_id: UUID, req: AddBlacklistRequest) -> BlacklistResponse:
    container = get_container()
    dto = AddBlacklistInput(
        reason=req.reason,
        note=req.note,
        created_by=UserId(req.created_by) if req.created_by else UserId.generate(),
    )
    result = await container.candidate_crud.add_to_blacklist(
        _DEFAULT_TENANT, CandidateId(candidate_id), dto
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    entry = result.value
    return BlacklistResponse(
        candidate_id=entry.candidate_id.value,
        reason=entry.reason.value,
        note=entry.note,
        created_by=entry.created_by.value,
    )


@router.get(
    "/{candidate_id}/blacklist",
    response_model=BlacklistResponse | None,
    summary="Проверить статус blacklist кандидата",
)
async def get_blacklist_status(candidate_id: UUID) -> BlacklistResponse | None:
    container = get_container()
    result = await container.candidate_crud.get_blacklist_status(
        _DEFAULT_TENANT, CandidateId(candidate_id)
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    entry = result.value
    if entry is None:
        return None
    return BlacklistResponse(
        candidate_id=entry.candidate_id.value,
        reason=entry.reason.value,
        note=entry.note,
        created_by=entry.created_by.value,
    )


@router.delete(
    "/{candidate_id}/blacklist",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить кандидата из blacklist",
)
async def remove_from_blacklist(candidate_id: UUID) -> None:
    container = get_container()
    result = await container.candidate_crud.remove_from_blacklist(
        _DEFAULT_TENANT, CandidateId(candidate_id)
    )
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )


# ---------------------------------------------------------------------------
# Bulk import (JUGO-105)
# ---------------------------------------------------------------------------


@router.post(
    ":import",
    response_model=BulkImportResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Массовый импорт кандидатов (JSON)",
)
async def bulk_import(req: BulkImportRequest) -> BulkImportResultResponse:
    container = get_container()
    rows = [
        BulkImportRow(
            full_name=r.full_name,
            source=r.source,
            headline=r.headline,
            skills=r.skills,
            location=r.location,
        )
        for r in req.rows
    ]
    result = await container.bulk_import_candidates.execute(_DEFAULT_TENANT, rows)
    if is_error(result):
        raise HTTPException(
            status_code=_err_status(result.error.code.value), detail=result.error.message
        )
    bulk = result.value
    return BulkImportResultResponse(
        created=len(bulk.created),
        errors=len(bulk.errors),
        error_details=bulk.errors,
    )


# ---------------------------------------------------------------------------
# Upload resume (existing)
# ---------------------------------------------------------------------------


@router.post(
    "/upload-resume",
    response_model=CandidateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить резюме → AI-парсинг → создать кандидата",
)
async def upload_resume(
    file: UploadFile,
    source: CandidateSource = CandidateSource.DIRECT,
) -> CandidateResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый формат. Допустимо: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой (макс {MAX_FILE_SIZE // (1024 * 1024)} МБ)",
        )

    container = get_container()
    result = await container.upload_resume.execute(
        tenant_id=_DEFAULT_TENANT,
        content=content,
        filename=file.filename or "resume.txt",
        idempotency_key=IdempotencyKey(f"upload-{file.filename}-{len(content)}"),
        source=source,
    )

    if is_error(result):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.message)
    return _to_response(result.value)
