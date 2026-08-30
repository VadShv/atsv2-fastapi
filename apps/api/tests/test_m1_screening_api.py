"""Тесты E-40: M1 Screening API.

Эндпоинты скрининга кандидатов: run, get, by-application, list, stale,
override, invalidate. Использует StubAIGateway (ATS_STUB_MODE=1).

Полный флоу: создать вакансию (с авто-генерацией критериев) → запустить
скрининг → проверить результат → override/invalidate.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.shared.ids import TenantId

client = TestClient(app)

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

# Валидный текст резюме (>= 50 символов, не спам)
GOOD_RESUME = (
    "Python developer with 5 years of experience in FastAPI, PostgreSQL, "
    "and async programming. Built microservices and REST APIs."
)


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# Хелпер: создать вакансию с критериями через API
# ---------------------------------------------------------------------------


def _create_vacancy_with_criteria() -> str:
    """Создать вакансию и вернуть vacancy_id (критерии генерируются авто)."""
    resp = client.post(
        "/api/v1/vacancies",
        json={
            "title": "Senior Python Developer",
            "seniority": "senior",
            "team": "Backend",
            "description": "We need a senior Python developer for our backend team.",
            "requirements": ["Python", "FastAPI", "PostgreSQL"],
            "nice_to_have": ["Docker", "Kubernetes"],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["criteria"]["provenance_id"], "Criteria should be generated"
    return data["vacancy_id"]


# ---------------------------------------------------------------------------
# POST /screening/run — запуск скрининга
# ---------------------------------------------------------------------------


class TestRunScreening:
    """Тесты запуска скрининга кандидата."""

    def test_run_screening_success(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        app_id = str(uuid.uuid4())
        cand_id = str(uuid.uuid4())

        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": app_id,
                "candidate_id": cand_id,
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        assert data["application_id"] == app_id
        assert data["vacancy_id"] == vacancy_id
        assert "recommendation" in data
        assert data["recommendation"] in (
            "strong_yes",
            "yes",
            "borderline",
            "no",
            "strong_no",
        )
        assert isinstance(data["total_score"], (int, float))
        assert 0.0 <= data["total_score"] <= 1.0
        assert isinstance(data["evaluations"], list)
        assert len(data["evaluations"]) > 0
        ev = data["evaluations"][0]
        assert "criterion_name" in ev
        assert 0.0 <= ev["score"] <= 1.0
        assert ev["weight"] >= 0

    def test_run_screening_blacklisted_rejected(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()

        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
                "is_blacklisted": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        assert data["recommendation"] == "rejected_level0"
        assert data["level0"]["rejected"] is True
        assert data["level0"]["reason"] == "blacklisted"
        assert data["evaluations"] == []

    def test_run_screening_spam_rejected(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        spam_text = " ".join(["http://spam.com"] * 6)

        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": spam_text,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["recommendation"] == "rejected_level0"
        assert data["level0"]["reason"] == "spam"

    def test_run_screening_unreadable_rejected(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()

        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": "too short",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["recommendation"] == "rejected_level0"
        assert data["level0"]["reason"] == "unreadable"

    def test_run_screening_hard_disqualify_rejected(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()

        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
                "hard_disqualify_reasons": ["underage"],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["recommendation"] == "rejected_level0"
        assert "hard_disqualify" in data["level0"]["reason"]

    def test_run_screening_vacancy_not_found(self) -> None:
        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": str(uuid.uuid4()),
                "resume_text": GOOD_RESUME,
            },
        )
        assert resp.status_code == 400
        assert "не найден" in resp.json()["detail"].lower() or "not found" in resp.json()[
            "detail"
        ].lower()

    def test_run_screening_duplicate_rejected(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()

        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
                "is_duplicate": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["recommendation"] == "rejected_level0"
        assert data["level0"]["reason"] == "duplicate"

    def test_run_screening_empty_resume_validation(self) -> None:
        """Пустой resume_text отклоняется Pydantic (min_length=1)."""
        vacancy_id = _create_vacancy_with_criteria()
        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": "",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /screening/{screening_id} — результат по ID
# ---------------------------------------------------------------------------


class TestGetScreening:
    """Тесты получения результата скрининга по ID."""

    def test_get_screening_success(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        resp = client.get(f"/api/v1/screening/{screening_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == screening_id

    def test_get_screening_not_found(self) -> None:
        resp = client.get(f"/api/v1/screening/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /screening/by-application/{application_id}
# ---------------------------------------------------------------------------


class TestGetScreeningByApplication:
    """Тесты получения результата скрининга по заявке."""

    def test_get_by_application_success(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        app_id = str(uuid.uuid4())
        client.post(
            "/api/v1/screening/run",
            json={
                "application_id": app_id,
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )

        resp = client.get(f"/api/v1/screening/by-application/{app_id}")
        assert resp.status_code == 200
        assert resp.json()["application_id"] == app_id

    def test_get_by_application_not_found(self) -> None:
        resp = client.get(f"/api/v1/screening/by-application/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /screening/vacancy/{vacancy_id} — список для вакансии
# ---------------------------------------------------------------------------


class TestListScreeningByVacancy:
    """Тесты списка результатов скрининга для вакансии."""

    def test_list_by_vacancy_returns_results(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        for _ in range(3):
            client.post(
                "/api/v1/screening/run",
                json={
                    "application_id": str(uuid.uuid4()),
                    "candidate_id": str(uuid.uuid4()),
                    "vacancy_id": vacancy_id,
                    "resume_text": GOOD_RESUME,
                },
            )

        resp = client.get(f"/api/v1/screening/vacancy/{vacancy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["results"]) == 3

    def test_list_by_vacancy_empty(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        resp = client.get(f"/api/v1/screening/vacancy/{vacancy_id}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_by_vacancy_pagination(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        for _ in range(5):
            client.post(
                "/api/v1/screening/run",
                json={
                    "application_id": str(uuid.uuid4()),
                    "candidate_id": str(uuid.uuid4()),
                    "vacancy_id": vacancy_id,
                    "resume_text": GOOD_RESUME,
                },
            )

        resp = client.get(f"/api/v1/screening/vacancy/{vacancy_id}?limit=2&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 2


# ---------------------------------------------------------------------------
# GET /screening/vacancy/{vacancy_id}/stale
# ---------------------------------------------------------------------------


class TestListStaleScreening:
    """Тесты устаревших результатов скрининга."""

    def test_list_stale_empty_by_default(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )

        resp = client.get(f"/api/v1/screening/vacancy/{vacancy_id}/stale")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_stale_after_invalidate(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        client.post(f"/api/v1/screening/{screening_id}/invalidate")

        resp = client.get(f"/api/v1/screening/vacancy/{vacancy_id}/stale")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# POST /screening/{screening_id}/override — подтвердить/оспорить (JUGO-407)
# ---------------------------------------------------------------------------


class TestOverrideScreening:
    """Тесты подтверждения/оспаривания результата скрининга."""

    def test_override_confirm(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        resp = client.post(
            f"/api/v1/screening/{screening_id}/override",
            json={"action": "confirm", "user_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["override_action"] == "confirm"
        assert data["overridden_by"] != ""

    def test_override_dispute(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        resp = client.post(
            f"/api/v1/screening/{screening_id}/override",
            json={"action": "dispute", "user_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        assert resp.json()["override_action"] == "dispute"

    def test_override_invalid_action(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        resp = client.post(
            f"/api/v1/screening/{screening_id}/override",
            json={"action": "bogus", "user_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    def test_override_not_found(self) -> None:
        resp = client.post(
            f"/api/v1/screening/{uuid.uuid4()}/override",
            json={"action": "confirm", "user_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /screening/{screening_id}/invalidate — пометить устаревшим (JUGO-408)
# ---------------------------------------------------------------------------


class TestInvalidateScreening:
    """Тесты пометки результата устаревшим."""

    def test_invalidate_success(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        resp = client.post(f"/api/v1/screening/{screening_id}/invalidate")
        assert resp.status_code == 200
        assert resp.json()["is_stale"] is True

    def test_invalidate_not_found(self) -> None:
        resp = client.post(f"/api/v1/screening/{uuid.uuid4()}/invalidate")
        assert resp.status_code == 404

    def test_invalidate_idempotent(self) -> None:
        """Повторная пометка устаревшим не ломает результат."""
        vacancy_id = _create_vacancy_with_criteria()
        run_resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        screening_id = run_resp.json()["id"]

        r1 = client.post(f"/api/v1/screening/{screening_id}/invalidate")
        r2 = client.post(f"/api/v1/screening/{screening_id}/invalidate")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["is_stale"] is True


# ---------------------------------------------------------------------------
# Whitebox: provenance доступен в результате
# ---------------------------------------------------------------------------


class TestWhiteboxProvenance:
    """Whitebox AI: provenance и reasoning доступны в результате скрининга."""

    def test_completed_screening_has_provenance(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "gateway_id": "stub",  # extra field ignored
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        # AI-скрининг должен иметь provenance (не level0 reject)
        assert data["recommendation"] != "rejected_level0"
        assert data["provenance_id"] is not None
        assert data["criteria_provenance_id"] is not None
        assert data["non_ai"] is False

    def test_level0_reject_has_no_provenance(self) -> None:
        vacancy_id = _create_vacancy_with_criteria()
        resp = client.post(
            "/api/v1/screening/run",
            json={
                "application_id": str(uuid.uuid4()),
                "candidate_id": str(uuid.uuid4()),
                "vacancy_id": vacancy_id,
                "resume_text": GOOD_RESUME,
                "is_blacklisted": True,
            },
        )
        data = resp.json()
        assert data["recommendation"] == "rejected_level0"
        assert data["provenance_id"] is None
        assert data["non_ai"] is False
