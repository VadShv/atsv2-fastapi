"""API-слой candidates: HTTP-эндпоинт загрузки резюме."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.candidates.domain.candidate import CandidateSource
from ats.shared.ids import IdempotencyKey, TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/candidates", tags=["candidates"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

# Лимит размера загружаемого файла (10 МБ)
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}


class CandidateResponse(BaseModel):
    id: UUID
    full_name: str
    headline: str = ""
    skills: list[str] = Field(default_factory=list)
    source: str
    resume_provenance: UUID | None = None


def _to_response(candidate) -> CandidateResponse:
    return CandidateResponse(
        id=candidate.id.value,
        full_name=candidate.full_name,
        headline=candidate.headline,
        skills=list(candidate.skills),
        source=candidate.source.value,
        resume_provenance=candidate.resume_provenance,
    )


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
    # Валидация расширения
    from pathlib import Path

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый формат. Допустимо: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Чтение содержимого с лимитом размера
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.message
        )
    return _to_response(result.value)
