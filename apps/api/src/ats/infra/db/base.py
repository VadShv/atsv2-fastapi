"""Базовый класс ORM-моделей и примесь мультитенантности (RLS).

SECURE FIRST: каждая tenant-таблица наследует TenantMixin и получает RLS-политику,
ограничивающую строки по app.tenant_id (устанавливается в сессии на каждый запрос).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""

    pass


class TenantMixin:
    """Примесь: tenant_id + created_at/updated_at.

    Таблицы с этим миксином получают RLS-политику в миграции.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TimestampMixin:
    """Только временные метки, без tenant (для глобальных таблиц)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> UUID:
    return uuid4()
