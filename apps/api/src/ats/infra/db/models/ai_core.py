"""ORM-модели AI Core: provenance ledger (whitebox AI).

Append-only хранилище провенанса. Любой AI-артефакт ссылается на provenance.id,
что позволяет объяснить и воспроизвести любое AI-решение.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class ProvenanceORM(Base, TenantMixin):
    """Запись провенанса AI-вызова (whitebox).

    Поля соответствуют ProvenanceRecord из домена. Append-only: обновляется только
    флаг human_verified (через отдельный UPDATE).
    """

    __tablename__ = "provenance"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    skill: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_refs: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    raw_output: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_output: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    human_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    reasoning_trace: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # non_ai=True, если LLM был недоступен и использован детерминированный fallback
    non_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
