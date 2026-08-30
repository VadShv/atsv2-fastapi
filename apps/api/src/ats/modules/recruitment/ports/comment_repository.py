"""Порт: репозиторий тредов комментариев (JUGO-143)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from ats.modules.recruitment.domain.comment import CommentThread
from ats.shared.ids import TenantId


@runtime_checkable
class CommentRepository(Protocol):
    async def save_thread(self, thread: CommentThread) -> UUID:
        """Сохранить тред (create или update)."""
        ...

    async def get_thread(self, tenant_id: TenantId, thread_id: UUID) -> CommentThread | None:
        """Получить тред по ID."""
        ...

    async def list_by_application(
        self, tenant_id: TenantId, application_id: UUID
    ) -> list[CommentThread]:
        """Все треды заявки."""
        ...
