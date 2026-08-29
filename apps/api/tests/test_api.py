"""HTTP-тесты API: вакансии, заявки, pipeline кандидатов."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.main import app

client = TestClient(app)


def setup_function() -> None:
    reset_container()


class TestVacanciesAPI:
    def test_create_vacancy_with_ai_criteria(self) -> None:
        resp = client.post(
            "/api/v1/vacancies",
            json={
                "title": "Middle Python Developer",
                "seniority": "middle",
                "team": "Backend",
                "description": "Backend на FastAPI+PostgreSQL. Python, REST, async.",
                "requirements": ["Python", "FastAPI"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "vacancy_id" in data
        assert data["criteria"]["provenance_id"] is not None
        assert data["criteria"]["summary"] is not None

    def test_create_vacancy_validation_error(self) -> None:
        resp = client.post(
            "/api/v1/vacancies",
            json={"title": "", "seniority": "middle", "team": "X", "description": "d"},
        )
        assert resp.status_code == 422  # Pydantic validation


class TestApplicationsAPI:
    def test_full_pipeline_flow(self) -> None:
        # 1. Создать кандидата через use case (нет HTTP-эндпоинта кандидатов ещё)
        from ats.infra.container_helpers import get_container
        from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
        from ats.shared.ids import TenantId

        tenant = TenantId.from_string("00000000-0000-0000-0000-000000000001")
        container = get_container()
        candidate = Candidate.create(
            tenant_id=tenant,
            full_name="Иван Иванов",
            source=CandidateSource.DATABASE,
            headline="Python developer",
            skills=["Python", "FastAPI"],
        )
        import asyncio

        asyncio.run(container.candidate_repository.save(candidate))

        # 2. Создать вакансию
        vacancy_resp = client.post(
            "/api/v1/vacancies",
            json={
                "title": "Backend Dev",
                "seniority": "middle",
                "team": "Core",
                "description": "desc",
            },
        )
        vacancy_id = vacancy_resp.json()["vacancy_id"]

        # 3. Создать заявку
        app_resp = client.post(
            "/api/v1/applications",
            json={"candidate_id": str(candidate.id.value), "vacancy_id": vacancy_id},
        )
        assert app_resp.status_code == 201
        app_data = app_resp.json()
        app_id = app_data["id"]
        assert app_data["stage"] == "new"

        # 4. Перевести: new → screening
        move1 = client.post(
            f"/api/v1/applications/{app_id}/move",
            json={"to_stage": "screening", "reason": "resume ok"},
        )
        assert move1.status_code == 200
        assert move1.json()["stage"] == "screening"
        assert len(move1.json()["transitions"]) == 1

        # 5. Недопустимый переход: screening → hired (надо через interview, offer)
        move_bad = client.post(
            f"/api/v1/applications/{app_id}/move",
            json={"to_stage": "hired"},
        )
        assert move_bad.status_code == 409

        # 6. Корректный путь до hired
        for stage in ["interview", "offer", "hired"]:
            r = client.post(f"/api/v1/applications/{app_id}/move", json={"to_stage": stage})
            assert r.status_code == 200
        final = client.post(
            f"/api/v1/applications/{app_id}/move", json={"to_stage": "hired"}
        )
        assert final.json()["stage"] == "hired"
        assert final.json()["is_terminal"] is True

    def test_move_nonexistent_returns_404(self) -> None:
        from uuid import uuid4

        resp = client.post(
            f"/api/v1/applications/{uuid4()}/move",
            json={"to_stage": "screening"},
        )
        assert resp.status_code == 404

    def test_create_application_idempotent(self) -> None:
        from ats.infra.container_helpers import get_container
        from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
        from ats.shared.ids import TenantId
        import asyncio

        tenant = TenantId.from_string("00000000-0000-0000-0000-000000000001")
        container = get_container()
        candidate = Candidate.create(
            tenant_id=tenant,
            full_name="Петр Петров",
            source=CandidateSource.REFERRAL,
        )
        asyncio.run(container.candidate_repository.save(candidate))
        vacancy_resp = client.post(
            "/api/v1/vacancies",
            json={
                "title": "Dev",
                "seniority": "junior",
                "team": "X",
                "description": "d",
            },
        )
        vacancy_id = vacancy_resp.json()["vacancy_id"]

        r1 = client.post(
            "/api/v1/applications",
            json={"candidate_id": str(candidate.id.value), "vacancy_id": vacancy_id},
        )
        r2 = client.post(
            "/api/v1/applications",
            json={"candidate_id": str(candidate.id.value), "vacancy_id": vacancy_id},
        )
        assert r1.json()["id"] == r2.json()["id"]
