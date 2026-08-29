"""ORM-модели candidates: кандидат (CRM 360) + таблица поиска.

Candidate — обезличенный профиль (PII в PII-vault). candidates_search —
денормализованный индекс для гибридного поиска (tsvector + pgvector).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class CandidateORM(Base, TenantMixin):
    """Кандидат (persisted-вид агрегата Candidate). Обезличен."""

    __tablename__ = "candidates"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    pii_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headline: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
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
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
