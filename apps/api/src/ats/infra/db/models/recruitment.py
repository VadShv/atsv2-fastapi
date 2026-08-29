"""ORM-модели recruitment: вакансии, заявки, стадии пайплайна."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class VacancyORM(Base, TenantMixin):
    """Вакансия (persisted-вид агрегата Vacancy)."""

    __tablename__ = "vacancies"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    seniority: Mapped[str] = mapped_column(String(50), nullable=False)
    team: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    # Полное описание роли (вход для AI-генерации критериев)
    role_description: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    nice_to_have: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # provenance_id генерации критериев (whitebox)
    screening_criteria_provenance: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("provenance.id", ondelete="SET NULL"), nullable=True
    )


class PipelineStageORM(Base, TenantMixin):
    """Стадия пайплайна (как в Huntflow: Новый, Скрининг, Интервью, Оффер...).

    Настраивается per-tenant. Заявки кандидатов проходят по стадиям.
    """

    __tablename__ = "pipeline_stages"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
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
