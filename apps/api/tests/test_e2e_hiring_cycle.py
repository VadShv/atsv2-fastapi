"""E2E: полный ручной цикл найма через REST API (Гейт Волны 1).

Сценарий «охота до найма» — моделирует ручной workflow рекрутера:
1. Создать вакансию (AI генерирует критерии скрининга)
2. Опубликовать вакансию
3. Создать кандидата
4. Подать отклик (привязать кандидата к вакансии)
5. Пройти воронку: NEW → SCREENING → INTERVIEW → OFFER → HIRED
6. Проверить hired_count вакансии
7. Закрыть вакансию

Дополнительно: сценарий отклонения и повторного открытия.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.main import app

client = TestClient(app)

API = "/api/v1"


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_vacancy(title: str = "Senior Python Developer") -> dict:
    """Создать вакансию и вернуть полный ответ (vacancy_id + criteria)."""
    resp = client.post(
        f"{API}/vacancies",
        json={
            "title": title,
            "seniority": "senior",
            "team": "Platform",
            "description": "Разработка высоконагруженного бэкенда на FastAPI.",
            "requirements": ["Python 3.11+", "FastAPI", "PostgreSQL", "asyncio"],
            "nice_to_have": ["Kafka", "Redis"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_candidate(name: str = "Иван Иванов") -> str:
    resp = client.post(
        f"{API}/candidates",
        json={
            "full_name": name,
            "source": "direct",
            "headline": "Python Developer, 8 лет опыта",
            "skills": ["Python", "FastAPI", "PostgreSQL", "asyncio"],
            "location": "Москва",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_application(candidate_id: str, vacancy_id: str) -> str:
    resp = client.post(
        f"{API}/applications",
        json={
            "candidate_id": candidate_id,
            "vacancy_id": vacancy_id,
            "origin": "incoming",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _move_application(app_id: str, to_stage: str) -> dict:
    resp = client.post(
        f"{API}/applications/{app_id}/move",
        json={"to_stage": to_stage, "reason": f"-> {to_stage}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _transition_entries(timeline: dict) -> list[dict]:
    """Отфильтровать переходы из таймлайна (entries с event_type=transition)."""
    return [e for e in timeline["entries"] if e["event_type"] == "transition"]


# ---------------------------------------------------------------------------
# Happy path: полный цикл найма
# ---------------------------------------------------------------------------


class TestHiringHappyPath:
    """Гейт Волны 1: создать вакансию -> кандидат -> отклик -> найм."""

    def test_full_hiring_cycle(self) -> None:
        # 1. Создание вакансии + AI-критерии
        create_resp = _create_vacancy()
        vacancy_id = create_resp["vacancy_id"]
        assert create_resp["status"] == "draft"

        # AI-критерии должны быть сгенерированы (StubAIGateway)
        criteria = create_resp["criteria"]
        assert criteria is not None
        assert criteria["summary"] is not None
        assert len(criteria["groups"]) > 0
        assert criteria["scoring_logic"] is not None

        # 2. Публикация вакансии
        pub_resp = client.post(f"{API}/vacancies/{vacancy_id}/publish")
        assert pub_resp.status_code == 200
        assert pub_resp.json()["status"] == "open"

        # 3. Создание кандидата
        candidate_id = _create_candidate()

        # 4. Подача отклика
        app_id = _create_application(candidate_id, vacancy_id)

        # Проверка начального состояния
        app_resp = client.get(f"{API}/applications/{app_id}")
        assert app_resp.status_code == 200
        app_data = app_resp.json()
        assert app_data["stage"] == "new"
        assert app_data["is_active"] is True
        assert app_data["is_terminal"] is False
        assert app_data["is_rejected"] is False

        # 5. Воронка: NEW -> SCREENING
        moved = _move_application(app_id, "screening")
        assert moved["stage"] == "screening"
        assert len(moved["transitions"]) == 1

        # SCREENING -> INTERVIEW
        moved = _move_application(app_id, "interview")
        assert moved["stage"] == "interview"
        assert len(moved["transitions"]) == 2

        # INTERVIEW -> OFFER
        moved = _move_application(app_id, "offer")
        assert moved["stage"] == "offer"
        assert len(moved["transitions"]) == 3

        # OFFER -> HIRED
        moved = _move_application(app_id, "hired")
        assert moved["stage"] == "hired"
        assert moved["is_terminal"] is True
        assert moved["is_active"] is False  # терминальный — не активный
        assert len(moved["transitions"]) == 4

        # 6. Проверка hired_count на вакансии (JUGO-124)
        vacancy = client.get(f"{API}/vacancies/{vacancy_id}").json()
        assert vacancy["hired_count"] == 1

        # 7. Закрытие вакансии
        close_resp = client.post(f"{API}/vacancies/{vacancy_id}/close")
        assert close_resp.status_code == 200
        assert close_resp.json()["status"] == "closed"
        assert close_resp.json()["closed_at"] is not None

    def test_timeline_records_all_transitions(self) -> None:
        """Таймлайн заявки содержит всю историю переходов."""
        create_resp = _create_vacancy("DevOps Engineer")
        vacancy_id = create_resp["vacancy_id"]
        client.post(f"{API}/vacancies/{vacancy_id}/publish")
        candidate_id = _create_candidate("Пётр Петров")
        app_id = _create_application(candidate_id, vacancy_id)

        for stage in ("screening", "interview", "offer", "hired"):
            _move_application(app_id, stage)

        timeline = client.get(f"{API}/applications/{app_id}/timeline")
        assert timeline.status_code == 200
        timeline_data = timeline.json()

        transitions = _transition_entries(timeline_data)
        assert len(transitions) == 4
        stages_sequence = [t["metadata"]["to_stage"] for t in transitions]
        assert stages_sequence == ["screening", "interview", "offer", "hired"]


# ---------------------------------------------------------------------------
# Rejection path
# ---------------------------------------------------------------------------


class TestRejectionPath:
    """Отклонение кандидата и повторное открытие."""

    def test_reject_with_official_reason(self) -> None:
        create_resp = _create_vacancy("QA Engineer")
        vacancy_id = create_resp["vacancy_id"]
        client.post(f"{API}/vacancies/{vacancy_id}/publish")
        candidate_id = _create_candidate("Анна Смирнова")
        app_id = _create_application(candidate_id, vacancy_id)

        # Переход на screening, затем отказ
        _move_application(app_id, "screening")
        reject_resp = client.post(
            f"{API}/applications/{app_id}/reject",
            json={
                "reason_code": "no_suitable_candidates",
                "reason_label": "Не подошёл по техническим навыкам",
                "internal_note": "Слабый опыт автоматизации",
            },
        )
        assert reject_resp.status_code == 200
        rejected = reject_resp.json()
        assert rejected["stage"] == "rejected"
        assert rejected["is_rejected"] is True
        assert rejected["is_terminal"] is True
        assert rejected["rejection_reason_code"] == "no_suitable_candidates"
        assert rejected["rejection_reason_label"] is not None

    def test_rejected_can_return_to_new(self) -> None:
        """Отклонённый кандидат может быть возвращён в новую."""
        create_resp = _create_vacancy("Data Analyst")
        vacancy_id = create_resp["vacancy_id"]
        client.post(f"{API}/vacancies/{vacancy_id}/publish")
        candidate_id = _create_candidate("Сергей Сергеев")
        app_id = _create_application(candidate_id, vacancy_id)

        _move_application(app_id, "rejected")
        assert client.get(f"{API}/applications/{app_id}").json()["stage"] == "rejected"

        revived = _move_application(app_id, "new")
        assert revived["stage"] == "new"
        assert revived["is_rejected"] is False


# ---------------------------------------------------------------------------
# Vacancy lifecycle
# ---------------------------------------------------------------------------


class TestVacancyLifecycle:
    """Жизненный цикл вакансии: draft -> open -> on_hold -> open -> closed."""

    def test_hold_and_resume(self) -> None:
        create_resp = _create_vacancy("Product Manager")
        vacancy_id = create_resp["vacancy_id"]

        client.post(f"{API}/vacancies/{vacancy_id}/publish")
        assert client.get(f"{API}/vacancies/{vacancy_id}").json()["status"] == "open"

        hold_resp = client.post(f"{API}/vacancies/{vacancy_id}/hold")
        assert hold_resp.json()["status"] == "on_hold"

        # Повторная публикация из on_hold
        resume_resp = client.post(f"{API}/vacancies/{vacancy_id}/publish")
        assert resume_resp.status_code == 200
        assert resume_resp.json()["status"] == "open"

    def test_cancel_draft_vacancy(self) -> None:
        create_resp = _create_vacancy("Scrum Master")
        vacancy_id = create_resp["vacancy_id"]

        cancel_resp = client.post(f"{API}/vacancies/{vacancy_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "canceled"

    def test_references_endpoint(self) -> None:
        """Справочники доступны и содержат ожидаемые значения."""
        resp = client.get(f"{API}/vacancies/references")
        assert resp.status_code == 200
        data = resp.json()
        assert "middle" in data["seniorities"]
        assert "draft" in data["statuses"]
        assert "open" in data["statuses"]
        assert "remote" in data["work_formats"]
        assert len(data["rejection_reasons"]) > 0


# ---------------------------------------------------------------------------
# Multiple candidates on same vacancy
# ---------------------------------------------------------------------------


class TestMultipleCandidates:
    """Несколько кандидатов на одну вакансию, один нанят, другой отклонён."""

    def test_two_candidates_one_hired_one_rejected(self) -> None:
        create_resp = _create_vacancy("Team Lead")
        vacancy_id = create_resp["vacancy_id"]
        client.post(f"{API}/vacancies/{vacancy_id}/publish")

        # Кандидат 1 — будет нанят
        cand1 = _create_candidate("Алексей Морозов")
        app1 = _create_application(cand1, vacancy_id)

        # Кандидат 2 — будет отклонён
        cand2 = _create_candidate("Дмитрий Волков")
        app2 = _create_application(cand2, vacancy_id)

        # Список откликов по вакансии
        apps_list = client.get(f"{API}/applications?vacancy_id={vacancy_id}")
        assert apps_list.status_code == 200
        assert len(apps_list.json()) == 2

        # Кандидат 2 — отказ
        _move_application(app2, "screening")
        client.post(
            f"{API}/applications/{app2}/reject",
            json={
                "reason_code": "no_suitable_candidates",
                "reason_label": "Недостаточный лидерский опыт",
            },
        )

        # Кандидат 1 — найм
        for stage in ("screening", "interview", "offer", "hired"):
            _move_application(app1, stage)

        # Проверка hired_count
        vacancy = client.get(f"{API}/vacancies/{vacancy_id}").json()
        assert vacancy["hired_count"] == 1

        # Проверка статусов заявок
        app1_final = client.get(f"{API}/applications/{app1}").json()
        app2_final = client.get(f"{API}/applications/{app2}").json()
        assert app1_final["stage"] == "hired"
        assert app1_final["is_terminal"] is True
        assert app2_final["stage"] == "rejected"
        assert app2_final["is_rejected"] is True


# ---------------------------------------------------------------------------
# Idempotency: повторный отклик -> конфликт
# ---------------------------------------------------------------------------


class TestApplicationIdempotency:
    """JUGO-142: повторный активный отклик -> конфликт."""

    def test_duplicate_application_returns_409(self) -> None:
        create_resp = _create_vacancy("Backend Developer")
        vacancy_id = create_resp["vacancy_id"]
        client.post(f"{API}/vacancies/{vacancy_id}/publish")
        candidate_id = _create_candidate("Елена Кузнецова")

        # Первый отклик — OK
        resp1 = client.post(
            f"{API}/applications",
            json={
                "candidate_id": candidate_id,
                "vacancy_id": vacancy_id,
                "origin": "incoming",
            },
        )
        assert resp1.status_code == 201

        # Второй отклик того же кандидата на ту же вакансию -> конфликт
        resp2 = client.post(
            f"{API}/applications",
            json={
                "candidate_id": candidate_id,
                "vacancy_id": vacancy_id,
                "origin": "incoming",
            },
        )
        assert resp2.status_code in (409, 400)
