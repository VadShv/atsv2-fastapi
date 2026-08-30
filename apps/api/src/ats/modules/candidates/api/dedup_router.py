"""API-слой дедупликации кандидатов (JUGO-150..155).

Endpoints:
    POST   /candidates/{id}/contacts          — зарегистрировать контакт (HMAC-хэш)
    GET    /candidates/{id}/duplicates         — найти дубли (exact + fuzzy)
    GET    /candidates/duplicates              — фоновый поиск всех дублей
    GET    /candidates/contacts/check          — проверить существование контакта
    POST   /candidates/merge                   — объединить двух кандидатов
    POST   /candidates/merge/{merge_log_id}/rollback — откатить мердж (30 дней)
    GET    /candidates/{id}/merge-logs         — история мерджей кандидата
    POST   /candidates/{id}/auto-merge         — автомердж точных дублей (фича-флаг)
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.infra.middleware.problem_details import ProblemException
from ats.modules.candidates.domain.dedup import ContactKind
from ats.shared.ids import CandidateId, TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/candidates", tags=["dedup"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------


class RegisterContactRequest(BaseModel):
    kind: str = Field(description="phone|email|telegram|linkedin|github|other")
    value: str = Field(description="Значение контакта (шифруется, хранится хэш)")
    is_primary: bool = False


class ContactCheckResponse(BaseModel):
    exists: bool
    candidate_ids: list[str] = Field(default_factory=list)


class DuplicateMatchResponse(BaseModel):
    survivor_id: str
    duplicate_id: str
    confidence: str
    score: float
    matched_fields: list[str]


class DuplicateListResponse(BaseModel):
    matches: list[DuplicateMatchResponse]
    total: int


class MergeRequest(BaseModel):
    survivor_id: str = Field(description="ID кандидата-наследника")
    absorbed_id: str = Field(description="ID поглощаемого кандидата")


class MergeResponse(BaseModel):
    merge_log_id: str
    survivor_id: str
    absorbed_id: str
    status: str
    transferred_applications: int
    transferred_facts: int
    transferred_contact_hashes: int
    transferred_tags: int
    rollbackable_until: str


class MergeLogResponse(BaseModel):
    id: str
    survivor_id: str
    absorbed_id: str
    status: str
    merged_at: str
    rolled_back_at: str | None = None
    rollbackable: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_contact_kind(value: str) -> ContactKind:
    try:
        return ContactKind(value)
    except ValueError:
        raise ProblemException(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Validation Error",
            detail=f"Неизвестный тип контакта: {value}",
        ) from None


def _match_to_response(m) -> DuplicateMatchResponse:
    return DuplicateMatchResponse(
        survivor_id=str(m.survivor_id),
        duplicate_id=str(m.duplicate_id),
        confidence=m.confidence.value,
        score=m.score,
        matched_fields=list(m.matched_fields),
    )


# ---------------------------------------------------------------------------
# Static routes (must come before /{candidate_id} routes to avoid conflicts)
# ---------------------------------------------------------------------------


@router.get("/contacts/check", response_model=ContactCheckResponse)
async def check_contact(kind: str, value: str) -> ContactCheckResponse:
    """Проверить, существует ли уже контакт (при создании/импорте)."""
    container = get_container()
    ids = await container.dedup_use_case.check_contact_exists(
        _DEFAULT_TENANT, _to_contact_kind(kind), value
    )
    return ContactCheckResponse(
        exists=len(ids) > 0,
        candidate_ids=[str(i.value) for i in ids],
    )


@router.get("/duplicates", response_model=DuplicateListResponse)
async def find_all_duplicates(limit: int = 100) -> DuplicateListResponse:
    """Фоновый поиск всех дублей в тенанте."""
    container = get_container()
    matches = await container.dedup_use_case.find_all_duplicates(_DEFAULT_TENANT, limit)
    return DuplicateListResponse(
        matches=[_match_to_response(m) for m in matches],
        total=len(matches),
    )


@router.post("/merge", response_model=MergeResponse)
async def merge_candidates(req: MergeRequest) -> MergeResponse:
    """Объединить двух кандидатов."""
    container = get_container()
    result = await container.dedup_use_case.merge_candidates(
        _DEFAULT_TENANT,
        CandidateId.from_string(req.survivor_id),
        CandidateId.from_string(req.absorbed_id),
    )
    if is_error(result):
        code = result.error.code
        if code.value == "not_found":
            sc = status.HTTP_404_NOT_FOUND
        elif code.value == "conflict":
            sc = status.HTTP_409_CONFLICT
        else:
            sc = status.HTTP_400_BAD_REQUEST
        raise ProblemException(
            status_code=sc,
            title="Error",
            detail=result.error.message,
        )
    mr = result.value
    return MergeResponse(
        merge_log_id=str(mr.merge_log.id),
        survivor_id=str(mr.merge_log.survivor_id.value),
        absorbed_id=str(mr.merge_log.absorbed_id.value),
        status=mr.merge_log.status.value,
        transferred_applications=mr.transferred_applications,
        transferred_facts=mr.transferred_facts,
        transferred_contact_hashes=mr.transferred_contact_hashes,
        transferred_tags=mr.transferred_tags,
        rollbackable_until=mr.merge_log.expires_at.isoformat(),
    )


@router.post("/merge/{merge_log_id}/rollback", response_model=MergeLogResponse)
async def rollback_merge(merge_log_id: str) -> MergeLogResponse:
    """Откатить мердж (в пределах 30 дней)."""
    container = get_container()
    result = await container.dedup_use_case.rollback_merge(_DEFAULT_TENANT, merge_log_id)
    if is_error(result):
        code = result.error.code
        sc = status.HTTP_404_NOT_FOUND if code.value == "not_found" else status.HTTP_409_CONFLICT
        raise ProblemException(
            status_code=sc,
            title="Error",
            detail=result.error.message,
        )
    log = result.value
    return MergeLogResponse(
        id=str(log.id),
        survivor_id=str(log.survivor_id.value),
        absorbed_id=str(log.absorbed_id.value),
        status=log.status.value,
        merged_at=log.merged_at.isoformat(),
        rolled_back_at=log.rolled_back_at.isoformat() if log.rolled_back_at else None,
        rollbackable=log.is_rollbackable,
    )


# ---------------------------------------------------------------------------
# Parameterized routes (/{candidate_id}/...)
# ---------------------------------------------------------------------------


@router.post("/{candidate_id}/contacts", status_code=status.HTTP_201_CREATED)
async def register_contact(candidate_id: str, req: RegisterContactRequest) -> dict[str, str]:
    """Зарегистрировать контакт кандидата (HMAC-хэш для дедупа)."""
    container = get_container()
    result = await container.dedup_use_case.register_contact(
        _DEFAULT_TENANT,
        CandidateId.from_string(candidate_id),
        _to_contact_kind(req.kind),
        req.value,
        req.is_primary,
    )
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Validation Error",
            detail=result.error.message,
        )
    return {"status": "registered", "value_hash": result.value.value_hash}


@router.get("/{candidate_id}/duplicates", response_model=DuplicateListResponse)
async def find_duplicates(candidate_id: str, limit: int = 50) -> DuplicateListResponse:
    """Найти дубли кандидата (exact + fuzzy)."""
    container = get_container()
    cid = CandidateId.from_string(candidate_id)
    exact = await container.dedup_use_case.find_exact_duplicates(_DEFAULT_TENANT, cid)
    fuzzy = await container.dedup_use_case.find_fuzzy_duplicates(_DEFAULT_TENANT, cid, limit)
    all_matches = exact + fuzzy
    return DuplicateListResponse(
        matches=[_match_to_response(m) for m in all_matches],
        total=len(all_matches),
    )


@router.get("/{candidate_id}/merge-logs", response_model=list[MergeLogResponse])
async def list_merge_logs(
    candidate_id: str, include_rolled_back: bool = False
) -> list[MergeLogResponse]:
    """История мерджей кандидата."""
    container = get_container()
    logs = await container.dedup_repository.list_merge_logs(
        _DEFAULT_TENANT,
        CandidateId.from_string(candidate_id),
        include_rolled_back,
    )
    return [
        MergeLogResponse(
            id=str(log.id),
            survivor_id=str(log.survivor_id.value),
            absorbed_id=str(log.absorbed_id.value),
            status=log.status.value,
            merged_at=log.merged_at.isoformat(),
            rolled_back_at=log.rolled_back_at.isoformat() if log.rolled_back_at else None,
            rollbackable=log.is_rollbackable,
        )
        for log in logs
    ]


@router.post("/{candidate_id}/auto-merge")
async def auto_merge(candidate_id: str) -> dict:
    """Автомердж точных дублей (требует фича-флаг ATS_DEDUP_AUTO_MERGE=1)."""
    container = get_container()
    result = await container.dedup_use_case.auto_merge_exact(
        _DEFAULT_TENANT,
        CandidateId.from_string(candidate_id),
    )
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail=result.error.message,
        )
    if result.value is None:
        return {"status": "no_duplicates", "merged": False}
    mr = result.value
    return {
        "status": "merged",
        "merged": True,
        "merge_log_id": str(mr.merge_log.id),
        "transferred_applications": mr.transferred_applications,
    }
