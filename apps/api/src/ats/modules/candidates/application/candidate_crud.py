"""Use cases: CRUD кандидатов + факты + теги + blacklist.

USERFRIENDLY: простые DTO, понятные ошибки, Result-тип.
WHITEBOX AI: каждый факт хранит источник и confidence.
SECURE FIRST: blacklist только для admin/head_of_recruiting.
УСТОЙЧИВОСТЬ: patch-семантика обновления, идемпотентное сохранение.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
from ats.modules.candidates.domain.facts import (
    CandidateFact,
    FactId,
    FactSource,
    FactType,
)
from ats.modules.candidates.domain.tags import (
    BlacklistEntry,
    BlacklistReason,
    CandidateTag,
    TagId,
)
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.shared.ids import CandidateId, TenantId, UserId
from ats.shared.result import ErrorCode, Result, is_error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class CreateCandidateInput:
    full_name: str
    source: CandidateSource = CandidateSource.DIRECT
    headline: str = ""
    skills: list[str] = field(default_factory=list)
    location: str = ""
    pii_token: str | None = None


@dataclass
class UpdateCandidateInput:
    full_name: str | None = None
    headline: str | None = None
    skills: list[str] | None = None
    location: str | None = None


@dataclass
class AddFactInput:
    fact_type: FactType
    source: FactSource = FactSource.MANUAL
    content: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    pinned: bool = False
    confidence: float = 1.0
    source_ref: str | None = None


@dataclass
class AddTagInput:
    name: str
    color: str = "#6b7280"
    created_by: UserId | None = None


@dataclass
class AddBlacklistInput:
    reason: BlacklistReason
    note: str = ""
    created_by: UserId = field(default_factory=UserId.generate)


# ---------------------------------------------------------------------------
# Use cases
# ---------------------------------------------------------------------------


class CandidateCrudUseCase:
    """CRUD-операции над кандидатами: create, get, update, list, delete.

    Делегирует персистентность в CandidateRepository. Возвращает Result-тип
    для явной обработки ошибок (whitebox).
    """

    def __init__(self, candidates: CandidateRepository) -> None:
        self._candidates = candidates

    async def create(self, tenant_id: TenantId, dto: CreateCandidateInput) -> Result[Candidate]:
        if not dto.full_name.strip():
            return Result.err(ErrorCode.VALIDATION, "Candidate full_name is required")
        try:
            candidate = Candidate.create(
                tenant_id=tenant_id,
                full_name=dto.full_name,
                source=dto.source,
                pii_token=dto.pii_token,
                headline=dto.headline,
                skills=dto.skills,
                location=dto.location,
            )
        except ValueError as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))

        await self._candidates.save(candidate)
        logger.info("Candidate created: %s", candidate.id)
        return Result.ok(candidate)

    async def get(self, tenant_id: TenantId, candidate_id: CandidateId) -> Result[Candidate]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")
        return Result.ok(candidate)

    async def update(
        self, tenant_id: TenantId, candidate_id: CandidateId, dto: UpdateCandidateInput
    ) -> Result[Candidate]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")

        candidate.update_profile(
            full_name=dto.full_name,
            headline=dto.headline,
            skills=dto.skills,
            location=dto.location,
        )
        await self._candidates.save(candidate)
        return Result.ok(candidate)

    async def list(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> Result[list[Candidate]]:
        items = await self._candidates.list_by_tenant(tenant_id, limit, offset)
        return Result.ok(items)

    async def delete(self, tenant_id: TenantId, candidate_id: CandidateId) -> Result[bool]:
        deleted = await self._candidates.delete(tenant_id, candidate_id)
        if not deleted:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")
        return Result.ok(True)

    async def add_fact(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        dto: AddFactInput,
    ) -> Result[CandidateFact]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")

        from uuid import uuid4

        fact = CandidateFact(
            id=FactId(uuid4()),
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            fact_type=dto.fact_type,
            source=dto.source,
            content=dto.content,
            pinned=dto.pinned,
            confidence=dto.confidence,
            source_ref=dto.source_ref,
        )
        await self._candidates.add_fact(fact)
        return Result.ok(fact)

    async def list_facts(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> Result[list[CandidateFact]]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")
        facts = await self._candidates.list_facts(tenant_id, candidate_id)
        return Result.ok(facts)

    async def delete_fact(
        self, tenant_id: TenantId, candidate_id: CandidateId, fact_id: str
    ) -> Result[bool]:
        deleted = await self._candidates.delete_fact(tenant_id, candidate_id, fact_id)
        if not deleted:
            return Result.err(ErrorCode.NOT_FOUND, "Fact not found")
        return Result.ok(True)

    async def add_tag(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        dto: AddTagInput,
    ) -> Result[CandidateTag]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")

        from uuid import uuid4

        tag = CandidateTag(
            id=TagId(uuid4()),
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            name=dto.name,
            color=dto.color,
            created_by=dto.created_by,
        )
        await self._candidates.add_tag(tag)
        return Result.ok(tag)

    async def list_tags(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> Result[list[CandidateTag]]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")
        tags = await self._candidates.list_tags(tenant_id, candidate_id)
        return Result.ok(tags)

    async def remove_tag(
        self, tenant_id: TenantId, candidate_id: CandidateId, tag_id: str
    ) -> Result[bool]:
        deleted = await self._candidates.remove_tag(tenant_id, candidate_id, tag_id)
        if not deleted:
            return Result.err(ErrorCode.NOT_FOUND, "Tag not found")
        return Result.ok(True)

    async def add_to_blacklist(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        dto: AddBlacklistInput,
    ) -> Result[BlacklistEntry]:
        candidate = await self._candidates.get(tenant_id, candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")

        existing = await self._candidates.get_blacklist_entry(tenant_id, candidate_id)
        if existing is not None:
            return Result.err(ErrorCode.CONFLICT, "Candidate is already blacklisted")

        from uuid import uuid4

        entry = BlacklistEntry(
            id=uuid4(),
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            reason=dto.reason,
            note=dto.note,
            created_by=dto.created_by,
        )
        await self._candidates.add_to_blacklist(entry)
        logger.warning("Candidate %s added to blacklist: %s", candidate_id, dto.reason.value)
        return Result.ok(entry)

    async def get_blacklist_status(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> Result[BlacklistEntry | None]:
        entry = await self._candidates.get_blacklist_entry(tenant_id, candidate_id)
        return Result.ok(entry)

    async def remove_from_blacklist(
        self, tenant_id: TenantId, candidate_id: CandidateId
    ) -> Result[bool]:
        removed = await self._candidates.remove_from_blacklist(tenant_id, candidate_id)
        if not removed:
            return Result.err(ErrorCode.NOT_FOUND, "Blacklist entry not found")
        return Result.ok(True)


# ---------------------------------------------------------------------------
# Bulk import use case (JUGO-105)
# ---------------------------------------------------------------------------


@dataclass
class BulkImportRow:
    """Одна строка массового импорта кандидатов."""

    full_name: str
    source: CandidateSource = CandidateSource.DIRECT
    headline: str = ""
    skills: list[str] = field(default_factory=list)
    location: str = ""


@dataclass
class BulkImportResult:
    """Результат массового импорта."""

    created: list[Candidate] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.created) + len(self.errors)


class BulkImportCandidatesUseCase:
    """Массовый импорт кандидатов из списка строк (JSON/CSV-нормализованных).

    УСТОЙЧИВОСТЬ: ошибки в отдельных строках не прерывают импорт остальных.
    СКОРОСТЬ: каждый кандидат создаётся и сохраняется немедленно.
    """

    def __init__(
        self,
        candidates: CandidateRepository,
    ) -> None:
        self._candidates = candidates

    async def execute(
        self, tenant_id: TenantId, rows: list[BulkImportRow]
    ) -> Result[BulkImportResult]:
        if not rows:
            return Result.err(ErrorCode.VALIDATION, "No rows to import")

        result = BulkImportResult()
        crud = CandidateCrudUseCase(self._candidates)

        for idx, row in enumerate(rows):
            dto = CreateCandidateInput(
                full_name=row.full_name,
                source=row.source,
                headline=row.headline,
                skills=row.skills,
                location=row.location,
            )
            create_result = await crud.create(tenant_id, dto)
            if is_error(create_result):
                result.errors.append(
                    {
                        "row": str(idx),
                        "full_name": row.full_name,
                        "error": create_result.error.message,
                    }
                )
            else:
                result.created.append(create_result.value)

        logger.info("Bulk import: %d created, %d errors", len(result.created), len(result.errors))
        return Result.ok(result)
