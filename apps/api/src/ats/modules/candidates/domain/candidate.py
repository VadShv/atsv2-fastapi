"""Домен кандидатов: агрегат Candidate (CRM 360).

Кандидат — физлицо. Хранит обезличенный профиль (PII в PII-vault, Фаза audit).
У кандидата может быть несколько заявок (Application) на разные вакансии.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import CandidateId, TenantId


class CandidateSource(StrEnum):
    """Источник кандидата (как в Huntflow: разные каналы привлечения)."""

    REFERRAL = "referral"
    JOB_BOARD = "job_board"
    DATABASE = "database"
    AGENCY = "agency"
    DIRECT = "direct"
    LINKEDIN = "linkedin"
    OTHER = "other"


@dataclass(frozen=True)
class CandidateCreated(DomainEvent):
    candidate_id: UUID = field(default_factory=uuid4)
    full_name: str = ""
    source: str = ""
    resume_provenance_id: str | None = None


@dataclass
class Candidate(AggregateRoot):
    """Агрегат Candidate.

    Инварианты:
    - full_name обязателен (минимум ФИО для идентификации).
    - PII (контакты) хранятся отдельно в PII-vault, здесь — только токен-ссылка.
    """

    # non-default поля — первыми
    id: CandidateId
    tenant_id: TenantId
    full_name: str
    source: CandidateSource
    # default поля — после
    pii_token: str | None = None
    headline: str = ""
    skills: list[str] = field(default_factory=list)
    resume_provenance: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        full_name: str,
        source: CandidateSource,
        pii_token: str | None = None,
        headline: str = "",
        skills: list[str] | None = None,
    ) -> Candidate:
        if not full_name.strip():
            raise ValueError("Candidate full_name is required")
        candidate = cls(
            id=CandidateId.generate(),
            tenant_id=tenant_id,
            full_name=full_name.strip(),
            source=source,
            pii_token=pii_token,
            headline=headline,
            skills=list(skills or []),
        )
        candidate._record(
            CandidateCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={"full_name": candidate.full_name, "source": source.value},
                candidate_id=candidate.id.value,
                full_name=candidate.full_name,
                source=source.value,
                resume_provenance_id=(
                    str(candidate.resume_provenance) if candidate.resume_provenance else None
                ),
            )
        )
        return candidate
