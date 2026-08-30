"""Тесты E-31: Prompt Registry API.

Проверяет whitebox-управление промптами: список, детали, рендер, playground.
Использует StubAIGateway (ATS_STUB_MODE=1) — без реальной LLM.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.main import app

client = TestClient(app)

# Зарегистрированные промпты (из prompts/__init__.py)
SCREENING_ID = "screening_criteria"
SCREENING_VERSION = "1.0.0"
PARSE_ID = "parse_resume"
PARSE_VERSION = "1.0.0"


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# GET /api/v1/prompts — список
# ---------------------------------------------------------------------------


class TestListPrompts:
    """Тесты списка промптов."""

    def test_list_returns_all_registered_prompts(self) -> None:
        resp = client.get("/api/v1/prompts")
        assert resp.status_code == 200
        data = resp.json()
        ids = {(p["id"], p["version"]) for p in data["prompts"]}
        assert (SCREENING_ID, SCREENING_VERSION) in ids
        assert (PARSE_ID, PARSE_VERSION) in ids
        assert data["total"] == len(data["prompts"])

    def test_list_prompt_has_required_fields(self) -> None:
        resp = client.get("/api/v1/prompts")
        data = resp.json()
        screening = next(
            p for p in data["prompts"] if p["id"] == SCREENING_ID
        )
        assert screening["name"] == "Generate Screening Criteria"
        assert screening["output_format"] == "json"
        assert screening["output_schema"] == "ScreeningCriteriaOutput"
        assert "role_description" in screening["variables"]
        assert "vacancy_title" in screening["variables"]
        assert "seniority" in screening["variables"]
        assert "team" in screening["variables"]

    def test_list_is_sorted_by_id_then_version(self) -> None:
        resp = client.get("/api/v1/prompts")
        data = resp.json()
        keys = [(p["id"], p["version"]) for p in data["prompts"]]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# GET /api/v1/prompts/{id}/{version} — детали
# ---------------------------------------------------------------------------


class TestGetPrompt:
    """Тесты деталей промпта."""

    def test_get_screening_detail(self) -> None:
        resp = client.get(f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == SCREENING_ID
        assert data["version"] == SCREENING_VERSION
        assert "Senior Recruiter" in data["system"]
        assert "{{role_description}}" in data["template"]
        assert data["output_format"] == "json"
        assert data["output_schema"] == "ScreeningCriteriaOutput"

    def test_get_parse_resume_detail(self) -> None:
        resp = client.get(f"/api/v1/prompts/{PARSE_ID}/{PARSE_VERSION}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == PARSE_ID
        assert "{{resume_text}}" in data["template"]
        assert data["output_schema"] == "ParsedResume"

    def test_get_nonexistent_prompt_404(self) -> None:
        resp = client.get("/api/v1/prompts/nonexistent/1.0.0")
        assert resp.status_code == 404
        assert "не найден" in resp.json()["detail"].lower() or "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/v1/prompts/{id}/{version}/render — рендер
# ---------------------------------------------------------------------------


class TestRenderPrompt:
    """Тесты рендера промпта переменными."""

    def test_render_substitutes_variables(self) -> None:
        resp = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/render",
            json={
                "variables": {
                    "role_description": "Python backend developer",
                    "vacancy_title": "Senior Python Developer",
                    "seniority": "senior",
                    "team": "Platform Team",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Переменные подставлены
        assert "Python backend developer" in data["user_message"]
        assert "Senior Python Developer" in data["user_message"]
        # Плейсхолдеров не осталось
        assert "{{role_description}}" not in data["user_message"]
        assert "{{vacancy_title}}" not in data["user_message"]
        # input_hash присутствует (whitebox)
        assert len(data["input_hash"]) == 64
        assert data["system"]

    def test_render_missing_variables_replaced_with_empty(self) -> None:
        resp = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/render",
            json={"variables": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Нет переменных → плейсхолдеры заменены на пустые строки
        assert "{{role_description}}" not in data["user_message"]

    def test_render_input_hash_deterministic(self) -> None:
        """Одинаковые переменные → одинаковый input_hash."""
        variables = {
            "role_description": "Test role",
            "vacancy_title": "Test Title",
            "seniority": "middle",
            "team": "Team A",
        }
        resp1 = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/render",
            json={"variables": variables},
        )
        resp2 = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/render",
            json={"variables": variables},
        )
        assert resp1.json()["input_hash"] == resp2.json()["input_hash"]

    def test_render_different_variables_different_hash(self) -> None:
        resp1 = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/render",
            json={"variables": {"role_description": "AAA", "vacancy_title": "T", "seniority": "s", "team": "x"}},
        )
        resp2 = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/render",
            json={"variables": {"role_description": "BBB", "vacancy_title": "T", "seniority": "s", "team": "x"}},
        )
        assert resp1.json()["input_hash"] != resp2.json()["input_hash"]

    def test_render_nonexistent_prompt_404(self) -> None:
        resp = client.post(
            "/api/v1/prompts/nonexistent/1.0.0/render",
            json={"variables": {}},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/prompts/{id}/{version}/playground — запуск через AIGateway
# ---------------------------------------------------------------------------


class TestPlayground:
    """Тесты playground: запуск промпта через StubAIGateway."""

    def test_playground_screening_structured(self) -> None:
        """Playground для screening_criteria → structured output."""
        resp = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/playground",
            json={
                "variables": {
                    "role_description": "Python developer with FastAPI",
                    "vacancy_title": "Middle Python Developer",
                    "seniority": "middle",
                    "team": "Backend Team",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt_id"] == SCREENING_ID
        assert data["prompt_version"] == SCREENING_VERSION
        assert data["output_format"] == "json"
        # Stub возвращает валидный structured output
        assert data["parsed_output"] is not None
        assert "groups" in data["parsed_output"]
        assert "summary" in data["parsed_output"]
        assert "scoring_logic" in data["parsed_output"]
        assert data["provenance_id"] is not None
        assert data["raw_output"]

    def test_playground_parse_resume_structured(self) -> None:
        """Playground для parse_resume → structured ParsedResume."""
        resp = client.post(
            f"/api/v1/prompts/{PARSE_ID}/{PARSE_VERSION}/playground",
            json={"variables": {"resume_text": "Иванов Иван, Python developer, 5 лет опыта"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed_output"] is not None
        assert "full_name" in data["parsed_output"]
        assert "skills" in data["parsed_output"]
        assert data["provenance_id"] is not None

    def test_playground_returns_model_and_usage(self) -> None:
        resp = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/playground",
            json={
                "variables": {
                    "role_description": "DevOps engineer",
                    "vacancy_title": "DevOps",
                    "seniority": "senior",
                    "team": "Infra",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"]
        assert isinstance(data["latency_ms"], int)
        assert isinstance(data["tokens_in"], int)
        assert isinstance(data["tokens_out"], int)
        assert isinstance(data["cost_usd"], (int, float))

    def test_playground_with_model_override(self) -> None:
        """Переопределение model в запросе."""
        resp = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/playground",
            json={
                "variables": {
                    "role_description": "QA engineer",
                    "vacancy_title": "QA",
                    "seniority": "middle",
                    "team": "QA Team",
                },
                "model": "custom-model-x",
            },
        )
        assert resp.status_code == 200
        # Stub gateway игнорирует модель, но запрос проходит без ошибки

    def test_playground_nonexistent_prompt_404(self) -> None:
        resp = client.post(
            "/api/v1/prompts/nonexistent/1.0.0/playground",
            json={"variables": {}},
        )
        assert resp.status_code == 404

    def test_playground_provenance_recorded(self) -> None:
        """Playground записывает provenance — можно получить через /ai/provenance."""
        resp = client.post(
            f"/api/v1/prompts/{SCREENING_ID}/{SCREENING_VERSION}/playground",
            json={
                "variables": {
                    "role_description": "Data Scientist",
                    "vacancy_title": "DS",
                    "seniority": "senior",
                    "team": "ML Team",
                }
            },
        )
        assert resp.status_code == 200
        provenance_id = resp.json()["provenance_id"]
        assert provenance_id

        # Проверяем, что provenance доступен через AI API
        prov_resp = client.get(f"/api/v1/ai/provenance/{provenance_id}")
        assert prov_resp.status_code == 200
        prov_data = prov_resp.json()
        assert prov_data["prompt_id"] == SCREENING_ID
        assert prov_data["prompt_version"] == SCREENING_VERSION
        assert prov_data["skill"] == "playground"
