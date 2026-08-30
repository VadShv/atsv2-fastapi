"""Тесты REST API: reject, timeline, comments, list, get (JUGO-141..144)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
from ats.shared.ids import CandidateId, TenantId, VacancyId

client = TestClient(app)

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def setup_function() -> None:
    reset_container()


def _create_candidate_and_vacancy(name: str = "API Тестов"):
    container = get_container()
    candidate = Candidate.create(
        tenant_id=TENANT,
        full_name=name,
        source=CandidateSource.DATABASE,
        headline="Dev",
        skills=["Python"],
    )
    asyncio.run(container.candidate_repository.save(candidate))

    vacancy_resp = client.post(
        "/api/v1/vacancies",
        json={
            "title": "API Dev",
            "seniority": "middle",
            "team": "X",
            "description": "desc",
        },
    )
    vacancy_id = vacancy_resp.json()["vacancy_id"]

    app_resp = client.post(
        "/api/v1/applications",
        json={
            "candidate_id": str(candidate.id.value),
            "vacancy_id": vacancy_id,
            "origin": "incoming",
        },
    )
    assert app_resp.status_code == 201
    return app_resp.json()["id"], candidate.id.value, vacancy_id


class TestApplicationsList:
    def test_list_applications_by_vacancy(self) -> None:
        app_id, _, vacancy_id = _create_candidate_and_vacancy()
        resp = client.get(f"/api/v1/applications?vacancy_id={vacancy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(a["id"] == app_id for a in data)

    def test_list_applications_no_filter_returns_empty(self) -> None:
        resp = client.get("/api/v1/applications")
        assert resp.status_code == 200
        assert resp.json() == []


class TestApplicationGet:
    def test_get_application_by_id(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        resp = client.get(f"/api/v1/applications/{app_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == app_id
        assert data["stage"] == "new"
        assert data["origin"] == "incoming"
        assert data["is_active"] is True
        assert data["is_rejected"] is False

    def test_get_nonexistent_returns_404(self) -> None:
        resp = client.get(f"/api/v1/applications/{uuid4()}")
        assert resp.status_code == 404


class TestApplicationReject:
    def test_reject_application(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        resp = client.post(
            f"/api/v1/applications/{app_id}/reject",
            json={
                "reason_code": "skills_mismatch",
                "reason_label": "Несоответствие навыков",
                "internal_note": "Нет опыта с FastAPI",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "rejected"
        assert data["is_rejected"] is True
        assert data["is_active"] is False
        assert data["rejection_reason_code"] == "skills_mismatch"
        assert data["rejection_reason_label"] == "Несоответствие навыков"

    def test_reject_nonexistent_returns_404(self) -> None:
        resp = client.post(
            f"/api/v1/applications/{uuid4()}/reject",
            json={"reason_code": "r", "reason_label": "R"},
        )
        assert resp.status_code == 404

    def test_reject_empty_reason_code_returns_422(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        resp = client.post(
            f"/api/v1/applications/{app_id}/reject",
            json={"reason_code": "", "reason_label": "R"},
        )
        assert resp.status_code == 422


class TestApplicationRepeatRules:
    def test_repeat_active_application_returns_409(self) -> None:
        """JUGO-142: повторная активная заявка → 409."""
        app_id, candidate_id, vacancy_id = _create_candidate_and_vacancy()
        resp = client.post(
            "/api/v1/applications",
            json={
                "candidate_id": str(candidate_id),
                "vacancy_id": vacancy_id,
            },
        )
        assert resp.status_code == 409

    def test_repeat_after_rejection_allowed(self) -> None:
        """JUGO-142: после отклонения → новая заявка разрешена."""
        app_id, candidate_id, vacancy_id = _create_candidate_and_vacancy()
        # Отклоняем
        client.post(
            f"/api/v1/applications/{app_id}/reject",
            json={"reason_code": "r", "reason_label": "R"},
        )
        # Новая заявка — разрешена
        resp = client.post(
            "/api/v1/applications",
            json={
                "candidate_id": str(candidate_id),
                "vacancy_id": vacancy_id,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["id"] != app_id


class TestApplicationTimeline:
    def test_timeline_endpoint(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        resp = client.get(f"/api/v1/applications/{app_id}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["application_id"] == app_id
        event_types = [e["event_type"] for e in data["entries"]]
        assert "created" in event_types

    def test_timeline_includes_transitions(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        client.post(
            f"/api/v1/applications/{app_id}/move",
            json={"to_stage": "screening", "reason": "ok"},
        )
        resp = client.get(f"/api/v1/applications/{app_id}/timeline")
        data = resp.json()
        event_types = [e["event_type"] for e in data["entries"]]
        assert "transition" in event_types

    def test_timeline_includes_rejection(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        client.post(
            f"/api/v1/applications/{app_id}/reject",
            json={"reason_code": "r", "reason_label": "R"},
        )
        resp = client.get(f"/api/v1/applications/{app_id}/timeline")
        data = resp.json()
        event_types = [e["event_type"] for e in data["entries"]]
        assert "rejection" in event_types

    def test_timeline_nonexistent_returns_404(self) -> None:
        resp = client.get(f"/api/v1/applications/{uuid4()}/timeline")
        assert resp.status_code == 404

    def test_timeline_includes_comments(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        # Создаём тред
        thread_resp = client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "Обсуждение", "observers": []},
        )
        assert thread_resp.status_code == 201
        thread_id = thread_resp.json()["id"]
        # Добавляем комментарий
        client.post(
            f"/api/v1/applications/{app_id}/threads/{thread_id}/comments",
            json={
                "author_id": str(uuid4()),
                "body": "Отличный кандидат",
                "is_private": False,
            },
        )
        # Проверяем таймлайн
        resp = client.get(f"/api/v1/applications/{app_id}/timeline")
        data = resp.json()
        event_types = [e["event_type"] for e in data["entries"]]
        assert "comment" in event_types


class TestCommentThreads:
    def test_create_thread(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        resp = client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "Обсуждение кандидата", "observers": ["user1"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Обсуждение кандидата"
        assert "user1" in data["observers"]
        assert data["comments"] == []

    def test_create_thread_nonexistent_application_404(self) -> None:
        resp = client.post(
            f"/api/v1/applications/{uuid4()}/threads",
            json={"title": "X"},
        )
        assert resp.status_code == 404

    def test_list_threads(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "Thread 1"},
        )
        client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "Thread 2"},
        )
        resp = client.get(f"/api/v1/applications/{app_id}/threads")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_add_comment_with_mention(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        thread_resp = client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "T"},
        )
        thread_id = thread_resp.json()["id"]
        author_id = uuid4()

        resp = client.post(
            f"/api/v1/applications/{app_id}/threads/{thread_id}/comments",
            json={
                "author_id": str(author_id),
                "body": "Посмотри @jane_smith это важно",
                "is_private": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        comment = data["comments"][0]
        assert "jane_smith" in comment["mentions"]
        # Упомянутый автоматически становится наблюдателем
        assert "jane_smith" in data["observers"]

    def test_add_private_comment(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        thread_resp = client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "T"},
        )
        thread_id = thread_resp.json()["id"]

        resp = client.post(
            f"/api/v1/applications/{app_id}/threads/{thread_id}/comments",
            json={
                "author_id": str(uuid4()),
                "body": "Скрытый комментарий",
                "is_private": True,
            },
        )
        assert resp.status_code == 200
        comment = resp.json()["comments"][0]
        assert comment["is_private"] is True

    def test_add_comment_with_attachments(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        thread_resp = client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "T"},
        )
        thread_id = thread_resp.json()["id"]

        resp = client.post(
            f"/api/v1/applications/{app_id}/threads/{thread_id}/comments",
            json={
                "author_id": str(uuid4()),
                "body": "Смотри вложение",
                "is_private": False,
                "attachments": ["file-001", "file-002"],
            },
        )
        assert resp.status_code == 200
        comment = resp.json()["comments"][0]
        assert len(comment["attachments"]) == 2

    def test_add_comment_nonexistent_thread_404(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        resp = client.post(
            f"/api/v1/applications/{app_id}/threads/{uuid4()}/comments",
            json={
                "author_id": str(uuid4()),
                "body": "test",
            },
        )
        assert resp.status_code == 404

    def test_multiple_mentions(self) -> None:
        app_id, _, _ = _create_candidate_and_vacancy()
        thread_resp = client.post(
            f"/api/v1/applications/{app_id}/threads",
            json={"title": "T"},
        )
        thread_id = thread_resp.json()["id"]

        resp = client.post(
            f"/api/v1/applications/{app_id}/threads/{thread_id}/comments",
            json={
                "author_id": str(uuid4()),
                "body": "@alice @bob @charlie проверьте",
                "is_private": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        comment = data["comments"][0]
        assert len(comment["mentions"]) == 3
        # Все упомянутые — наблюдатели
        assert "alice" in data["observers"]
        assert "bob" in data["observers"]
        assert "charlie" in data["observers"]
