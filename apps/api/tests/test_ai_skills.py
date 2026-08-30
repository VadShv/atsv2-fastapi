"""Тесты E-32: AI Skills API.

Прямые вызовы скиллов через API: список, запуск, регенерация критериев.
Использует StubAIGateway (ATS_STUB_MODE=1) — без реальной LLM.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.shared.ids import IdempotencyKey, TenantId

client = TestClient(app)

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# GET /api/v1/skills — список
# ---------------------------------------------------------------------------


class TestListSkills:
    """Тесты списка доступных скиллов."""

    def test_list_returns_all_skills(self) -> None:
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200
        data = resp.json()
        ids = {s["id"] for s in data["skills"]}
        assert "generate_screening_criteria" in ids
        assert "parse_resume" in ids
        assert data["total"] == len(data["skills"])

    def test_skill_has_metadata(self) -> None:
        resp = client.get("/api/v1/skills")
        data = resp.json()
        screening = next(
            s for s in data["skills"] if s["id"] == "generate_screening_criteria"
        )
        assert screening["prompt_id"] == "screening_criteria"
        assert screening["prompt_version"] == "1.0.0"
        assert screening["output_schema"] == "ScreeningCriteriaOutput"
        assert "role_description" in screening["variables"]

    def test_parse_resume_skill_has_resume_text_variable(self) -> None:
        resp = client.get("/api/v1/skills")
        data = resp.json()
        parse_skill = next(s for s in data["skills"] if s["id"] == "parse_resume")
        assert parse_skill["variables"] == ["resume_text"]


# ---------------------------------------------------------------------------
# POST /api/v1/skills/{skill_id}/run — запуск скилла
# ---------------------------------------------------------------------------


class TestRunSkill:
    """Тесты прямого запуска скилла."""

    def test_run_screening_criteria(self) -> None:
        resp = client.post(
            "/api/v1/skills/generate_screening_criteria/run",
            json={
                "variables": {
                    "role_description": "Python developer with FastAPI and PostgreSQL",
                    "vacancy_title": "Middle Python Developer",
                    "seniority": "middle",
                    "team": "Backend Team",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill_id"] == "generate_screening_criteria"
        assert data["parsed_output"] is not None
        assert "groups" in data["parsed_output"]
        assert "summary" in data["parsed_output"]
        assert data["provenance_id"]
        assert data["error"] is None

    def test_run_parse_resume(self) -> None:
        resp = client.post(
            "/api/v1/skills/parse_resume/run",
            json={
                "variables": {
                    "resume_text": "Иванов Иван. Python developer, 5 лет опыта. FastAPI, PostgreSQL."
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill_id"] == "parse_resume"
        assert data["parsed_output"] is not None
        assert "full_name" in data["parsed_output"]
        assert "skills" in data["parsed_output"]
        assert data["provenance_id"]

    def test_run_skill_provenance_recorded(self) -> None:
        """Запуск скилла записывает provenance — доступен через /ai/provenance."""
        resp = client.post(
            "/api/v1/skills/generate_screening_criteria/run",
            json={
                "variables": {
                    "role_description": "DevOps engineer",
                    "vacancy_title": "Senior DevOps",
                    "seniority": "senior",
                    "team": "Infra",
                }
            },
        )
        assert resp.status_code == 200
        provenance_id = resp.json()["provenance_id"]

        prov_resp = client.get(f"/api/v1/ai/provenance/{provenance_id}")
        assert prov_resp.status_code == 200
        prov_data = prov_resp.json()
        assert prov_data["skill"] == "generate_screening_criteria"
        assert prov_data["prompt_id"] == "screening_criteria"

    def test_run_skill_returns_model_and_usage(self) -> None:
        resp = client.post(
            "/api/v1/skills/generate_screening_criteria/run",
            json={
                "variables": {
                    "role_description": "QA engineer",
                    "vacancy_title": "QA",
                    "seniority": "middle",
                    "team": "QA Team",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"]
        assert isinstance(data["latency_ms"], int)
        assert isinstance(data["tokens_in"], int)
        assert isinstance(data["tokens_out"], int)

    def test_run_nonexistent_skill_404(self) -> None:
        resp = client.post(
            "/api/v1/skills/nonexistent_skill/run",
            json={"variables": {}},
        )
        assert resp.status_code == 404

    def test_run_parse_resume_empty_text_returns_error(self) -> None:
        """Пустой текст резюме → Result.err, возвращается как error (не 500)."""
        resp = client.post(
            "/api/v1/skills/parse_resume/run",
            json={"variables": {"resume_text": "   "}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is not None
        assert data["parsed_output"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/skills/vacancies/{vacancy_id}/regenerate-criteria
# ---------------------------------------------------------------------------


class TestRegenerateCriteria:
    """Тесты регенерации критериев для существующей вакансии."""

    def _create_vacancy(self) -> str:
        """Создать вакансию и вернуть её ID."""
        resp = client.post(
            "/api/v1/vacancies",
            json={
                "title": "Senior Python Developer",
                "seniority": "senior",
                "team": "Platform Team",
                "description": "Python developer with FastAPI, PostgreSQL, Docker experience",
                "requirements": ["Python 3.10+", "FastAPI", "PostgreSQL"],
                "nice_to_have": ["Docker", "Kubernetes"],
            },
        )
        assert resp.status_code == 201
        return resp.json()["vacancy_id"]

    def test_regenerate_criteria_success(self) -> None:
        vacancy_id = self._create_vacancy()

        resp = client.post(f"/api/v1/skills/vacancies/{vacancy_id}/regenerate-criteria")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vacancy_id"] == vacancy_id
        assert data["criteria_provenance_id"]
        assert data["criteria"] is not None
        assert "groups" in data["criteria"]
        assert data["error"] is None

    def test_regenerate_criteria_provenance_linked_to_vacancy(self) -> None:
        """После регенерации вакансия содержит новый provenance_id."""
        vacancy_id = self._create_vacancy()

        # Регенерация
        regen_resp = client.post(
            f"/api/v1/skills/vacancies/{vacancy_id}/regenerate-criteria"
        )
        assert regen_resp.status_code == 200
        new_provenance = regen_resp.json()["criteria_provenance_id"]

        # Проверяем вакансию
        vac_resp = client.get(f"/api/v1/vacancies/{vacancy_id}")
        assert vac_resp.status_code == 200
        vac_data = vac_resp.json()
        assert vac_data["screening_criteria_provenance"] == new_provenance

    def test_regenerate_criteria_provenance_different_from_original(self) -> None:
        """Регенерация создаёт новый provenance (отличный от исходного)."""
        create_resp = client.post(
            "/api/v1/vacancies",
            json={
                "title": "Data Scientist",
                "seniority": "senior",
                "team": "ML Team",
                "description": "ML engineer with Python, PyTorch, NLP experience",
            },
        )
        assert create_resp.status_code == 201
        original_provenance = create_resp.json()["criteria"]["provenance_id"]

        regen_resp = client.post(
            f"/api/v1/skills/vacancies/{create_resp.json()['vacancy_id']}/regenerate-criteria"
        )
        assert regen_resp.status_code == 200
        new_provenance = regen_resp.json()["criteria_provenance_id"]

        assert new_provenance != original_provenance

    def test_regenerate_criteria_nonexistent_vacancy_404(self) -> None:
        resp = client.post(
            "/api/v1/skills/vacancies/00000000-0000-0000-0000-000000000999/regenerate-criteria"
        )
        assert resp.status_code == 404
