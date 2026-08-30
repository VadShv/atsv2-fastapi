"""ORM-модель comment_threads: треды комментариев на заявках (JUGO-143).

CommentThread — тред с наблюдателями и вложенными комментариями (JSONB).
Comment — отдельное сообщение с @упоминаниями, приватностью, вложениями.
created_at/updated_at наследуются от TenantMixin.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ats.infra.db.base import Base, TenantMixin


class CommentThreadORM(Base, TenantMixin):
    """Тред комментариев на заявке (JUGO-143).

    comments — JSONB-массив объектов Comment (с mentions, is_private, attachments).
    observers — JSONB-массив строк (ID пользователей-наблюдателей).
    created_at/updated_at — наследуются от TenantMixin.
    """

    __tablename__ = "comment_threads"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    observers: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    comments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
