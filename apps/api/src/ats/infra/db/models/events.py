"""ORM-модели: outbox (устойчивость) и audit log (secure-first).

Outbox: события пишутся в ту же транзакцию, что и агрегат → воркер диспетчит.
Гарантия at-least-once → обработчики идемпотентны.
Audit: append-only журнал действий пользователей.

JUGO-033: audit_log партиционирован по месяцам (PARTITION BY RANGE created_at).
Primary key: (id, created_at) — требование декларативного партиционирования.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class OutboxMessageORM(Base, TenantMixin):
    """Outbox-сообщение: надёжная доставка доменных событий (контракт §4.3).

    Воркер (outbox-relay) вычитывает необработанные (processed_at IS NULL),
    публикует в Redis Streams, ставит processed_at. Идемпотентность — на стороне
    обработчика (processed_events / inbox).
    """

    __tablename__ = "outbox"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # event_type в dot.notation (напр. vacancy.created) — по контракту конверта
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), default="system", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Полная сериализация конверта события (JSON) — на публикацию в стрим
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Сколько раз пытались отправить (для DLQ)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditLogORM(Base, TenantMixin):
    """Append-only журнал действий (secure-first, compliance).

    ТЗ §15: кто, что, когда, откуда (IP/UA), trace_id.
    Записи никогда не обновляются/удаляются (immutable).

    JUGO-033: партиционирована по месяцам (PARTITION BY RANGE created_at).
    Primary key: (id, created_at) — требование декларативного партиционирования.
    """

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # created_at — часть PK (требование партиционирования по RANGE)
    # TenantMixin уже добавляет created_at, но для партиционирования
    # он должен быть в PK. SQLAlchemy обработает это через __table_args__.
    actor_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Детали изменения (до/после)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
