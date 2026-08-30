"""ORM-модель applications: заявка кандидата на вакансии (pipeline).

JUGO-140: расширение полей — origin, current_stage_id, stage_entered_at,
screening_score, risk_level, rejection fields, resume_id.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class ApplicationORM(Base, TenantMixin):
    """Заявка: кандидат на вакансии, со стадией пайплайна и историей.

    transitions — JSONB-массив записей StageTransitionRecord (append-only).
    score/score_provenance — AI-скоринг заявки (whitebox).
    JUGO-140: origin, current_stage_id, stage_entered_at, screening_score,
    risk_level, rejection_reason_code/label, internal_rejection_note, resume_id.
    """

    __tablename__ = "applications"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vacancy_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    origin: Mapped[str] = mapped_column(String(30), default="incoming", nullable=False)
    current_stage_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    stage_entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transitions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_provenance: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("provenance.id", ondelete="SET NULL"),
        nullable=True,
    )
    screening_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    rejection_reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejection_reason_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    internal_rejection_note: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
