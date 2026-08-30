"""Тесты домена Comment: треды, упоминания, наблюдатели, приватность (JUGO-143)."""

from __future__ import annotations

from uuid import uuid4

from ats.modules.recruitment.domain.comment import Comment, CommentThread
from ats.shared.ids import TenantId, UserId

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def _make_thread(title: str = "Test Thread") -> CommentThread:
    return CommentThread.create(
        tenant_id=TENANT,
        application_id=uuid4(),
        title=title,
    )


class TestCommentThread:
    def test_create_thread(self) -> None:
        thread = _make_thread("Обсуждение")
        assert thread.title == "Обсуждение"
        assert thread.comments == []
        assert thread.observers == []

    def test_create_with_observers(self) -> None:
        thread = CommentThread.create(
            tenant_id=TENANT,
            application_id=uuid4(),
            title="T",
            observers=["user1", "user2"],
        )
        assert len(thread.observers) == 2

    def test_add_comment(self) -> None:
        thread = _make_thread()
        author = UserId(uuid4())
        comment = thread.add_comment(author, "Тестовое сообщение")
        assert len(thread.comments) == 1
        assert comment.body == "Тестовое сообщение"
        assert comment.author_id == author

    def test_add_comment_publishes_event(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "test")
        events = thread.collect_events()
        assert len(events) == 1
        assert type(events[0]).__name__ == "CommentPosted"


class TestCommentMentions:
    def test_extract_single_mention(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Привет @alice посмотри")
        assert "alice" in thread.comments[0].mentions

    def test_extract_multiple_mentions(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "@alice @bob и @charlie")
        assert len(thread.comments[0].mentions) == 3

    def test_no_mentions(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Просто текст без упоминаний")
        assert thread.comments[0].mentions == []

    def test_mention_auto_adds_observer(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Проверь @jane это")
        assert "jane" in thread.observers

    def test_duplicate_mention_does_not_duplicate_observer(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "@jane текст @jane ещё")
        assert thread.observers.count("jane") == 1


class TestCommentPrivacy:
    def test_private_comment(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Скрыто", is_private=True)
        assert thread.comments[0].is_private is True

    def test_public_comment_default(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Публично")
        assert thread.comments[0].is_private is False

    def test_get_public_comments_filters_private(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Публичный 1")
        thread.add_comment(UserId(uuid4()), "Скрытый", is_private=True)
        thread.add_comment(UserId(uuid4()), "Публичный 2")
        public = thread.get_public_comments()
        assert len(public) == 2

    def test_get_all_comments_includes_private(self) -> None:
        thread = _make_thread()
        thread.add_comment(UserId(uuid4()), "Публичный")
        thread.add_comment(UserId(uuid4()), "Скрытый", is_private=True)
        all_comments = thread.get_all_comments()
        assert len(all_comments) == 2


class TestCommentAttachments:
    def test_add_attachment(self) -> None:
        comment = Comment.create(
            thread_id=uuid4(),
            author_id=UserId(uuid4()),
            body="test",
            attachments=["file-1"],
        )
        assert len(comment.attachments) == 1
        comment.add_attachment("file-2")
        assert len(comment.attachments) == 2

    def test_no_attachments_default(self) -> None:
        comment = Comment.create(
            thread_id=uuid4(),
            author_id=UserId(uuid4()),
            body="test",
        )
        assert comment.attachments == []


class TestCommentEdit:
    def test_edit_updates_body(self) -> None:
        comment = Comment.create(
            thread_id=uuid4(),
            author_id=UserId(uuid4()),
            body="Оригинал",
        )
        comment.edit("Изменённый текст")
        assert comment.body == "Изменённый текст"

    def test_edit_recalculates_mentions(self) -> None:
        comment = Comment.create(
            thread_id=uuid4(),
            author_id=UserId(uuid4()),
            body="Без упоминаний",
        )
        assert comment.mentions == []
        comment.edit("Теперь с @alice")
        assert "alice" in comment.mentions


class TestCommentThreadObservers:
    def test_add_observer(self) -> None:
        thread = _make_thread()
        thread.add_observer("user1")
        assert "user1" in thread.observers

    def test_add_duplicate_observer(self) -> None:
        thread = _make_thread()
        thread.add_observer("user1")
        thread.add_observer("user1")
        assert thread.observers.count("user1") == 1

    def test_remove_observer(self) -> None:
        thread = _make_thread()
        thread.add_observer("user1")
        thread.remove_observer("user1")
        assert "user1" not in thread.observers
