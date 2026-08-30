"""ORM-модель applications: заявка кандидата на вакансию (pipeline)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class ApplicationORM(Base, TenantMixin):
    """Заявка: кандидат на вакансии, со стадией пайплайна и историей.

    transitions — JSONB-массив записей StageTransition (append-only).
    score/score_provenance — AI-скоринг заявки (whitebox).
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
    transitions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_provenance: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("provenance.id", ondelete="SET NULL"),
        nullable=True,
    )
