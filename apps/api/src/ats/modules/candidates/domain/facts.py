"""Домен кандидатов: факты профиля (CRM 360).

Факт — структурированная запись о кандидате (опыт, навык, образование, язык).
Источник факта: resume_version, manual, import, ai_inference.
Закреплённый факт (pinned=True) не перезаписывается автообновлением из резюме.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID

from ats.shared.ids import CandidateId, TenantId


class FactType(StrEnum):
    """Тип факта профиля."""

    EXPERIENCE = "experience"
    SKILL = "skill"
    EDUCATION = "education"
    LANGUAGE = "language"
    CERTIFICATION = "certification"


class FactSource(StrEnum):
    """Источник факта — для whitebox-прозрачности."""

    RESUME_VERSION = "resume_version"
    MANUAL = "manual"
    IMPORT = "import"
    AI_INFERENCE = "ai_inference"


@dataclass(frozen=True)
class FactId:
    value: UUID


@dataclass
class CandidateFact:
    """Один факт профиля кандидата.

    WHITEBOX AI: каждый факт знает свой источник и confidence.
    УСТОЙЧИВОСТЬ: pinned-факты защищены от автообновления.
    """

    id: FactId
    tenant_id: TenantId
    candidate_id: CandidateId
    fact_type: FactType
    source: FactSource
    content: dict[str, str | int | float | bool | None]
    pinned: bool = False
    confidence: float = 1.0
    source_ref: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def can_be_overwritten_by(self, new_source: FactSource) -> bool:
        """Можно ли перезаписать этот факт новым источником."""
        if self.pinned:
            return False
        # Ручные факты не перезаписываются автоисточниками
        return not (
            self.source == FactSource.MANUAL
            and new_source
            in (
                FactSource.RESUME_VERSION,
                FactSource.AI_INFERENCE,
                FactSource.IMPORT,
            )
        )

    def to_payload(self) -> dict[str, str]:
        return {
            "fact_id": str(self.id.value),
            "candidate_id": str(self.candidate_id.value),
            "fact_type": self.fact_type.value,
            "source": self.source.value,
            "pinned": str(self.pinned),
        }


def build_experience_fact(
    tenant_id: TenantId,
    candidate_id: CandidateId,
    company: str,
    position: str,
    start_date: date | None = None,
    end_date: date | None = None,
    description: str = "",
    source: FactSource = FactSource.RESUME_VERSION,
    source_ref: str | None = None,
) -> CandidateFact:
    """Создать факт опыта работы."""
    from uuid import uuid4

    return CandidateFact(
        id=FactId(uuid4()),
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        fact_type=FactType.EXPERIENCE,
        source=source,
        content={
            "company": company,
            "position": position,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "description": description,
        },
        source_ref=source_ref,
    )


def build_skill_fact(
    tenant_id: TenantId,
    candidate_id: CandidateId,
    skill_name: str,
    level: str = "intermediate",
    source: FactSource = FactSource.RESUME_VERSION,
    source_ref: str | None = None,
) -> CandidateFact:
    """Создать факт навыка."""
    from uuid import uuid4

    return CandidateFact(
        id=FactId(uuid4()),
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        fact_type=FactType.SKILL,
        source=source,
        content={
            "skill_name": skill_name,
            "level": level,
        },
        source_ref=source_ref,
    )
