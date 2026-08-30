"""ORM-модели candidates: кандидат (CRM 360) + таблица поиска + факты + теги + blacklist.

Candidate — обезличенный профиль (PII в PII-vault). candidates_search —
денормализованный индекс для гибридного поиска (tsvector + pgvector).

candidate_facts — структурированные факты (опыт, навыки, образование, языки).
candidate_tags — пользовательские теги/метки для группировки.
candidate_blacklist — жёсткий список блокировок (SECURE FIRST).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class CandidateORM(Base, TenantMixin):
    """Кандидат (persisted-вид агрегата Candidate). Обезличен."""

    __tablename__ = "candidates"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    pii_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headline: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    location: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    resume_provenance: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("provenance.id", ondelete="SET NULL"),
        nullable=True,
    )


class CandidateSearchORM(Base):
    """Поисковый индекс кандидата: tsvector + embedding + jsonb metadata.

    Денормализован из Candidate + ParsedResume. Перестраивается при индексации.
    Composite PK (tenant_id, candidate_id). embedding — text (кастуется в vector).
    """

    __tablename__ = "candidates_search"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    search_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    search_tsv: Mapped[str] = Column(TSVECTOR, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class CandidateFactORM(Base, TenantMixin):
    """Структурированный факт профиля кандидата (WHITEBOX AI).

    Каждый факт знает свой источник (resume_version, manual, import, ai_inference)
    и confidence. pinned-факты защищены от автообновления.
    """

    __tablename__ = "candidate_facts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    pinned: Mapped[bool] = mapped_column(default=False, nullable=False)
    confidence: Mapped[float] = mapped_column(default=1.0, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CandidateTagORM(Base, TenantMixin):
    """Пользовательский тег кандидата для группировки."""

    __tablename__ = "candidate_tags"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#6b7280", nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)


class CandidateBlacklistORM(Base, TenantMixin):
    """Запись в blacklist — блокирует создание новых откликов (SECURE FIRST).

    Только admin/head_of_recruiting может добавить в blacklist.
    """

    __tablename__ = "candidate_blacklist"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
