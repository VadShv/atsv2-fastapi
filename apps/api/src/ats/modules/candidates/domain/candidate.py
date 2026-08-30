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


@dataclass(frozen=True)
class CandidateUpdated(DomainEvent):
    """Событие обновления профиля кандидата."""

    candidate_id: UUID = field(default_factory=uuid4)
    full_name: str = ""
    fields_changed: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResumeAttached(DomainEvent):
    """Событие привязки новой версии резюме к кандидату."""

    candidate_id: UUID = field(default_factory=uuid4)
    resume_provenance_id: str = ""


@dataclass
class Candidate(AggregateRoot):
    """Агрегат Candidate.

    Инварианты:
    - full_name обязателен (минимум ФИО для идентификации).
    - PII (контакты) хранятся отдельно в PII-vault, здесь — только токен-ссылка.
    - updated_at обновляется при любом изменении профиля.
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
    location: str = ""
    resume_provenance: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
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
        location: str = "",
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
            location=location,
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

    def update_profile(
        self,
        *,
        full_name: str | None = None,
        headline: str | None = None,
        skills: list[str] | None = None,
        location: str | None = None,
    ) -> None:
        """Обновить поля профиля. Записывает событие CandidateUpdated.

        Только непустые аргументы применяются (patch-семантика).
        """
        changed: list[str] = []
        if full_name is not None and full_name.strip() and full_name != self.full_name:
            self.full_name = full_name.strip()
            changed.append("full_name")
        if headline is not None and headline != self.headline:
            self.headline = headline
            changed.append("headline")
        if skills is not None and skills != self.skills:
            self.skills = list(skills)
            changed.append("skills")
        if location is not None and location != self.location:
            self.location = location
            changed.append("location")

        if changed:
            self.updated_at = datetime.now(UTC)
            self._record(
                CandidateUpdated(
                    event_id=uuid4(),
                    occurred_at=self.updated_at,
                    tenant_id=self.tenant_id.value,
                    payload={"fields_changed": list(changed)},
                    candidate_id=self.id.value,
                    full_name=self.full_name,
                    fields_changed=tuple(changed),
                )
            )

    def attach_resume(self, provenance_id: UUID) -> None:
        """Привязать новую версию резюме (provenance-ссылку на AI-вызов парсинга).

        WHITEBOX AI: кандидат хранит ссылку на конкретный AI-вызов, который
        распарсил резюме — это позволяет проследить происхождение данных.
        """
        self.resume_provenance = provenance_id
        self.updated_at = datetime.now(UTC)
        self._record(
            ResumeAttached(
                event_id=uuid4(),
                occurred_at=self.updated_at,
                tenant_id=self.tenant_id.value,
                payload={"resume_provenance_id": str(provenance_id)},
                candidate_id=self.id.value,
                resume_provenance_id=str(provenance_id),
            )
        )

    def to_registry_dict(self) -> dict[str, str | list[str] | None]:
        """Сериализация в dict для реестра/поискового индекса.

        Используется при индексации и маппинге в ORM.
        """
        return {
            "id": str(self.id.value),
            "tenant_id": str(self.tenant_id.value),
            "full_name": self.full_name,
            "source": self.source.value,
            "headline": self.headline,
            "skills": list(self.skills),
            "location": self.location,
            "pii_token": self.pii_token,
            "resume_provenance": (str(self.resume_provenance) if self.resume_provenance else None),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
