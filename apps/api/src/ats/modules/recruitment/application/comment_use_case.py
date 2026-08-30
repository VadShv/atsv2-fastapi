"""Use case: управление тредами комментариев на заявках (JUGO-143).

Создание тредов, добавление комментариев, управление наблюдателями.
@упоминания автоматически добавляют пользователей в наблюдатели.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.modules.recruitment.domain.comment import CommentThread
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.modules.recruitment.ports.comment_repository import CommentRepository
from ats.shared.ids import TenantId, UserId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


class CommentUseCase:
    """CRUD для тредов комментариев на заявках."""

    def __init__(
        self,
        comments: CommentRepository,
        applications: ApplicationRepository,
    ) -> None:
        self._comments = comments
        self._applications = applications

    async def create_thread(
        self,
        tenant_id: TenantId,
        application_id: UUID,
        title: str = "",
        observers: list[str] | None = None,
    ) -> Result[CommentThread]:
        app = await self._applications.get(tenant_id, application_id)
        if app is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Заявка не найдена",
                {"application_id": str(application_id)},
            )

        thread = CommentThread.create(
            tenant_id=tenant_id,
            application_id=application_id,
            title=title,
            observers=observers,
        )
        await self._comments.save_thread(thread)
        logger.info("Comment thread created: application=%s", application_id)
        return Result.ok(thread)

    async def add_comment(
        self,
        tenant_id: TenantId,
        thread_id: UUID,
        author_id: UserId,
        body: str,
        is_private: bool = False,
        attachments: list[str] | None = None,
    ) -> Result[CommentThread]:
        thread = await self._comments.get_thread(tenant_id, thread_id)
        if thread is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Тред комментариев не найден",
                {"thread_id": str(thread_id)},
            )

        thread.add_comment(
            author_id=author_id,
            body=body,
            is_private=is_private,
            attachments=attachments,
        )
        await self._comments.save_thread(thread)
        logger.info(
            "Comment added: thread=%s author=%s private=%s",
            thread_id,
            author_id,
            is_private,
        )
        return Result.ok(thread)

    async def list_threads(self, tenant_id: TenantId, application_id: UUID) -> list[CommentThread]:
        return await self._comments.list_by_application(tenant_id, application_id)

    async def add_observer(
        self, tenant_id: TenantId, thread_id: UUID, user_id: str
    ) -> Result[CommentThread]:
        thread = await self._comments.get_thread(tenant_id, thread_id)
        if thread is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Тред комментариев не найден",
                {"thread_id": str(thread_id)},
            )
        thread.add_observer(user_id)
        await self._comments.save_thread(thread)
        return Result.ok(thread)
