"""Тесты AI Core: парсинг structured output, ремонт JSON, промпт-реестр."""

from __future__ import annotations

from ats.infra.ai.json_repair import extract_json, parse_structured, repair_json
from ats.modules.ai_core.prompts.registry import get_prompt
from ats.modules.ai_core.prompts.schemas import (
    ScreeningCriteriaOutput,
)


class TestJSONRepair:
    def test_extract_from_markdown_fence(self) -> None:
        raw = '```json\n{"a": 1}\n```'
        assert extract_json(raw) == '{"a": 1}'

    def test_extract_with_surrounding_noise(self) -> None:
        raw = 'Вот ответ:\n{"a": 1}\nНадеюсь, помог.'
        assert extract_json(raw) == '{"a": 1}'

    def test_repair_trailing_comma(self) -> None:
        text = '{"a": 1, "b": 2,}'
        assert repair_json(text) == '{"a": 1, "b": 2}'

    def test_parse_structured_clean(self) -> None:
        raw = '{"summary": "x", "groups": [{"category": "hard_skill", "weight": 100, "criteria": [{"name": "n", "description": "d", "category": "hard_skill", "weight": 100, "verification": "v"}]}], "scoring_logic": "s", "reasoning": "r"}'
        parsed, _, repaired = parse_structured(raw, ScreeningCriteriaOutput)
        assert parsed is not None
        assert parsed.summary == "x"
        assert repaired is False

    def test_parse_structured_with_repair(self) -> None:
        raw = '```json\n{"summary": "x", "groups": [{"category": "hard_skill", "weight": 100, "criteria": [{"name": "n", "description": "d", "category": "hard_skill", "weight": 100, "verification": "v",}]}], "scoring_logic": "s", "reasoning": "r"}\n```'
        parsed, _, repaired = parse_structured(raw, ScreeningCriteriaOutput)
        assert parsed is not None
        assert repaired is True

    def test_parse_structured_invalid(self) -> None:
        parsed, _, _ = parse_structured("not json at all", ScreeningCriteriaOutput)
        assert parsed is None


class TestPromptRegistry:
    def test_screening_criteria_registered(self) -> None:
        spec = get_prompt("screening_criteria", "1.0.0")
        assert spec.id == "screening_criteria"
        assert spec.version == "1.0.0"
        assert spec.output_schema == "ScreeningCriteriaOutput"
        assert spec.temperature == 0.0

    def test_render_substitutes_variables(self) -> None:
        spec = get_prompt("screening_criteria", "1.0.0")
        rendered, input_hash = spec.render(
            {
                "role_description": "Python dev",
                "vacancy_title": "Backend",
                "seniority": "middle",
                "team": "Core",
            }
        )
        assert "Python dev" in rendered
        assert "Backend" in rendered
        assert len(input_hash) == 64  # sha256 hex

    def test_render_deterministic_hash(self) -> None:
        spec = get_prompt("screening_criteria", "1.0.0")
        vars_ = {"role_description": "x", "vacancy_title": "y", "seniority": "middle", "team": "z"}
        _, h1 = spec.render(vars_)
        _, h2 = spec.render(vars_)
        assert h1 == h2


class TestSchemaValidation:
    def test_weights_must_sum_to_100(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ScreeningCriteriaOutput.model_validate(
                {
                    "summary": "x",
                    "groups": [
                        {
                            "category": "hard_skill",
                            "weight": 50,
                            "criteria": [
                                {
                                    "name": "n",
                                    "description": "d",
                                    "category": "hard_skill",
                                    "weight": 50,
                                    "verification": "v",
                                }
                            ],
                        }
                    ],
                    "scoring_logic": "s",
                    "reasoning": "r",
                }
            )
