"""ORM-модели воронки: пресеты, стадии, снапшоты, переходы, решения НМ (JUGO-130..135)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class FunnelPresetORM(Base, TenantMixin):
    """Пресет воронки — настраиваемый пайплайн найма (JUGO-130)."""

    __tablename__ = "funnel_presets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)


class FunnelSnapshotORM(Base, TenantMixin):
    """Снапшот пресета на вакансию — immutable (JUGO-131)."""

    __tablename__ = "funnel_snapshots"

    vacancy_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    preset_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("funnel_presets.id", ondelete="SET NULL"),
        nullable=False,
    )
    stages: Mapped[list] = mapped_column(JSONB, nullable=False)


class StageTransitionORM(Base, TenantMixin):
    """Append-only журнал переходов по стадиям (JUGO-132)."""

    __tablename__ = "stage_transitions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_stage_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    to_stage_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), default="user", nullable=False)
    ai_provenance: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HMDecisionORM(Base, TenantMixin):
    """Решение нанимающего менеджера — immutable (JUGO-134)."""

    __tablename__ = "hm_decisions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)


class StageAutomationRuleORM(Base, TenantMixin):
    """Каркас правил автоперехода (JUGO-135)."""

    __tablename__ = "stage_automation_rules"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    stage_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_stage_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    block_auto_reject: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
