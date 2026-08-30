"""Домен комментариев: треды на заявках (JUGO-143).

CommentThread — тред комментариев, привязанный к заявке.
Comment — отдельное сообщение с @упоминаниями, наблюдателями, приватностью, вложениями.

SECURE FIRST: приватные комментарии видны только по правам signals:read.
USERFRIENDLY: @упоминания и наблюдатели для коллаборации.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import TenantId, UserId

# Regex для @упоминаний: @username или @uuid
_MENTION_PATTERN = re.compile(r"@([a-zA-Z0-9_.\-]+)")


@dataclass(frozen=True)
class CommentPosted(DomainEvent):
    """Событие: комментарий добавлен в тред."""

    thread_id: UUID = field(default_factory=uuid4)
    comment_id: UUID = field(default_factory=uuid4)
    application_id: UUID = field(default_factory=uuid4)
    author_id: str = ""
    is_private: bool = False


@dataclass
class Comment:
    """Отдельное сообщение в треде.

    Attributes:
        id: UUID комментария.
        thread_id: UUID родительского треда.
        author_id: ID автора (UserId).
        body: текст сообщения (может содержать @упоминания).
        is_private: приватный комментарий (виден по правам signals:read).
        mentions: список ID упомянутых пользователей (извлекаются из body).
        attachments: список URL/ID вложений.
        created_at: время создания.
        updated_at: время последнего редактирования.
    """

    id: UUID
    thread_id: UUID
    author_id: UserId
    body: str
    is_private: bool = False
    mentions: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        thread_id: UUID,
        author_id: UserId,
        body: str,
        is_private: bool = False,
        attachments: list[str] | None = None,
    ) -> Comment:
        mentions = _extract_mentions(body)
        return cls(
            id=uuid4(),
            thread_id=thread_id,
            author_id=author_id,
            body=body,
            is_private=is_private,
            mentions=mentions,
            attachments=attachments or [],
        )

    def edit(self, new_body: str) -> None:
        """Отредактировать текст комментария (пересчитывает упоминания)."""
        self.body = new_body
        self.mentions = _extract_mentions(new_body)
        self.updated_at = datetime.now(UTC)

    def add_attachment(self, attachment_id: str) -> None:
        self.attachments.append(attachment_id)
        self.updated_at = datetime.now(UTC)


@dataclass
class CommentThread(AggregateRoot):
    """Тред комментариев на заявке (JUGO-143).

    Attributes:
        id: UUID треда.
        application_id: UUID заявки, к которой привязан тред.
        tenant_id: ID тенанта.
        title: заголовок треда (опционально).
        observers: список ID наблюдателей (получают уведомления о новых комментариях).
        comments: список комментариев в треде.
        created_at: время создания треда.
        updated_at: время последнего обновления.
    """

    id: UUID
    application_id: UUID
    tenant_id: TenantId
    title: str = ""
    observers: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        application_id: UUID,
        title: str = "",
        observers: list[str] | None = None,
    ) -> CommentThread:
        thread = cls(
            id=uuid4(),
            application_id=application_id,
            tenant_id=tenant_id,
            title=title,
            observers=observers or [],
        )
        return thread

    def add_comment(
        self,
        author_id: UserId,
        body: str,
        is_private: bool = False,
        attachments: list[str] | None = None,
    ) -> Comment:
        """Добавить комментарий в тред.

        Автоматически добавляет упомянутых пользователей в наблюдатели.
        Публикует событие CommentPosted.
        """
        comment = Comment.create(
            thread_id=self.id,
            author_id=author_id,
            body=body,
            is_private=is_private,
            attachments=attachments,
        )
        self.comments.append(comment)

        for mention in comment.mentions:
            if mention not in self.observers:
                self.observers.append(mention)

        self.updated_at = datetime.now(UTC)
        self._record(
            CommentPosted(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={
                    "application_id": str(self.application_id),
                    "author_id": str(author_id.value),
                },
                thread_id=self.id,
                comment_id=comment.id,
                application_id=self.application_id,
                author_id=str(author_id.value),
                is_private=is_private,
            )
        )
        return comment

    def add_observer(self, user_id: str) -> None:
        """Добавить наблюдателя (получает уведомления о новых комментариях)."""
        if user_id not in self.observers:
            self.observers.append(user_id)
            self.updated_at = datetime.now(UTC)

    def remove_observer(self, user_id: str) -> None:
        if user_id in self.observers:
            self.observers.remove(user_id)
            self.updated_at = datetime.now(UTC)

    def get_public_comments(self) -> list[Comment]:
        """Только неприватные комментарии (для пользователей без signals:read)."""
        return [c for c in self.comments if not c.is_private]

    def get_all_comments(self) -> list[Comment]:
        """Все комментарии (требует прав signals:read для приватных)."""
        return list(self.comments)


def _extract_mentions(text: str) -> list[str]:
    """Извлечь @упоминания из текста."""
    return _MENTION_PATTERN.findall(text)
