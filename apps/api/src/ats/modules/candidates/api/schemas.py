"""Pydantic-схемы candidates для REST API (contracts).

Эти модели — контракт REST API v1 для кандидатов. Они генерируют OpenAPI-схему.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ats.modules.candidates.domain.candidate import CandidateSource
from ats.modules.candidates.domain.facts import FactSource, FactType
from ats.modules.candidates.domain.tags import BlacklistReason


class CandidateResponse(BaseModel):
    """Ответ: карточка кандидата (обезличенная)."""

    id: UUID
    full_name: str
    headline: str = ""
    skills: list[str] = Field(default_factory=list)
    location: str = ""
    source: str
    pii_token: str | None = None
    resume_provenance: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CandidateListResponse(BaseModel):
    """Ответ: список кандидатов с пагинацией."""

    items: list[CandidateResponse]
    total: int
    limit: int
    offset: int


class CreateCandidateRequest(BaseModel):
    """Запрос: создать кандидата вручную."""

    full_name: str = Field(min_length=1, max_length=500)
    source: CandidateSource = CandidateSource.DIRECT
    headline: str = Field(default="", max_length=500)
    skills: list[str] = Field(default_factory=list)
    location: str = Field(default="", max_length=500)
    pii_token: str | None = None


class UpdateCandidateRequest(BaseModel):
    """Запрос: обновить поля кандидата (patch-семантика)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=500)
    headline: str | None = Field(default=None, max_length=500)
    skills: list[str] | None = None
    location: str | None = Field(default=None, max_length=500)


class FactResponse(BaseModel):
    """Ответ: факт профиля кандидата."""

    id: UUID
    fact_type: str
    source: str
    content: dict[str, str | int | float | bool | None]
    pinned: bool = False
    confidence: float = 1.0
    source_ref: str | None = None


class FactListResponse(BaseModel):
    """Ответ: список фактов кандидата."""

    items: list[FactResponse]


class AddFactRequest(BaseModel):
    """Запрос: добавить факт кандидату."""

    fact_type: FactType
    source: FactSource = FactSource.MANUAL
    content: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    pinned: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_ref: str | None = None


class TagResponse(BaseModel):
    """Ответ: тег кандидата."""

    id: UUID
    name: str
    color: str = "#6b7280"
    created_by: UUID | None = None


class TagListResponse(BaseModel):
    """Ответ: список тегов кандидата."""

    items: list[TagResponse]


class AddTagRequest(BaseModel):
    """Запрос: добавить тег кандидату."""

    name: str = Field(min_length=1, max_length=200)
    color: str = Field(default="#6b7280", max_length=20)


class BlacklistResponse(BaseModel):
    """Ответ: запись blacklist."""

    candidate_id: UUID
    reason: str
    note: str = ""
    created_by: UUID


class AddBlacklistRequest(BaseModel):
    """Запрос: добавить кандидата в blacklist."""

    reason: BlacklistReason
    note: str = ""
    created_by: UUID | None = None


class BulkImportRowRequest(BaseModel):
    """Одна строка массового импорта."""

    full_name: str = Field(min_length=1, max_length=500)
    source: CandidateSource = CandidateSource.DIRECT
    headline: str = Field(default="", max_length=500)
    skills: list[str] = Field(default_factory=list)
    location: str = Field(default="", max_length=500)


class BulkImportRequest(BaseModel):
    """Запрос: массовый импорт кандидатов."""

    rows: list[BulkImportRowRequest] = Field(min_length=1, max_length=1000)


class BulkImportResultResponse(BaseModel):
    """Ответ: результат массового импорта."""

    created: int
    errors: int
    error_details: list[dict[str, str]] = Field(default_factory=list)
