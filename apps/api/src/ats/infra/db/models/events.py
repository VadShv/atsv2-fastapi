"""ORM-модели: outbox (устойчивость) и audit log (secure-first).

Outbox: события пишутся в ту же транзакцию, что и агрегат → воркер диспетчит.
Гарантия at-least-once → обработчики идемпотентны.
Audit: append-only журнал действий пользователей.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class OutboxMessageORM(Base, TenantMixin):
    """Outbox-сообщение: надёжная доставка доменных событий.

    Воркер вычитывает необработанные (processed_at IS NULL), диспетчит, ставит
    processed_at. Идемпотентность — на стороне обработчика.
    """

    __tablename__ = "outbox"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # Тип события (имя класса, напр. VacancyCreated)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Полная сериализация события (JSON)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Сколько раз пытались отправить (для DLQ)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditLogORM(Base, TenantMixin):
    """Append-only журнал действий (secure-first, compliance).

    Записи никогда не обновляются/удаляются (immutable).
    """

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Детали изменения (до/после)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), default="", nullable=False)
