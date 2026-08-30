"""ORM-модели: tenants, users, roles/permissions (RBAC).

SECURE FIRST: tenants — корень изоляции. Все tenant-таблицы ссылаются на tenants.id
и защищены RLS. users принадлежат tenant + имеют роли.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    """Организация-владелец (корень мультитенантности)."""

    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Role(Base, TimestampMixin):
    """Роль для RBAC (напр. admin, recruiter, hiring_manager, viewer)."""

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Разрешения как JSON-массив строк (ABAC-политики можно расширить позже)
    permissions: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class User(Base, TimestampMixin):
    """Пользователь системы (рекрутер, менеджер, админ)."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    # PII: ФИО хранится зашифрованным/токенизированным (PII-vault, Фаза audit)
    full_name_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
