"""ORM-модели recruitment: вакансии, заявки, стадии пайплайна, наборы критериев."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class VacancyORM(Base, TenantMixin):
    """Вакансия (persisted-вид агрегата Vacancy)."""

    __tablename__ = "vacancies"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    seniority: Mapped[str] = mapped_column(String(50), nullable=False)
    team: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    hiring_team: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # Полное описание роли (вход для AI-генерации критериев)
    role_description: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    nice_to_have: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # provenance_id генерации критериев (whitebox)
    screening_criteria_provenance: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("provenance.id", ondelete="SET NULL"), nullable=True
    )
    hired_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineStageORM(Base, TenantMixin):
    """Стадия пайплайна (как в Huntflow: Новый, Скрининг, Интервью, Оффер...).

    Настраивается per-tenant. Заявки кандидатов проходят по стадиям.
    """

    __tablename__ = "pipeline_stages"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    vacancy_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Порядок в пайплайне
    order: Mapped[int] = mapped_column(default=0, nullable=False)
    # Тип стадии для логики автоматизации
    stage_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)


class RequirementSetORM(Base, TenantMixin):
    """Версионируемый набор критериев скрининга для вакансии (JUGO-121).

    Только одна версия со status=active на вакансию в данный момент.
    Схема criteria — ScreeningCriteriaOutput (ТЗ §8.2).
    """

    __tablename__ = "vacancy_requirement_sets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    vacancy_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    origin: Mapped[str] = mapped_column(String(50), default="ai", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    provenance_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("provenance.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
