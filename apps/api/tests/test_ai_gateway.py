"""Тесты E-30: LLM Gateway (LiteLLM) + Redis CacheStore + AI API endpoints.

Мокирует litellm.acompletion / litellm.aembedding для тестирования без реальной LLM.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ats.infra.ai.cache import cache_key
from ats.infra.ai.redis_cache import RedisCacheStore
from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.modules.ai_core.domain.models import (
    AIRequest,
    ChatMessage,
    MessageRole,
    ProvenanceRecord,
)
from ats.modules.ai_core.prompts.registry import get_prompt
from ats.modules.ai_core.prompts.schemas import ScreeningCriteriaOutput
from ats.shared.ids import TenantId

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")
client = TestClient(app)


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# Helpers: mock LiteLLM responses
# ---------------------------------------------------------------------------


def _mock_completion_response(content: str, tokens_in: int = 100, tokens_out: int = 50):
    """Создать mock-ответ litellm.acompletion."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = tokens_in
    resp.usage.completion_tokens = tokens_out
    resp._hidden_params = {"response_cost": 0.001}
    return resp


def _make_ai_request(prompt_id: str = "screening_criteria", version: str = "1.0.0") -> AIRequest:
    spec = get_prompt(prompt_id, version)
    user_text, input_hash = spec.render(
        {
            "role_description": "Python developer with FastAPI",
            "vacancy_title": "Backend Dev",
            "seniority": "middle",
            "team": "Platform",
        }
    )
    return AIRequest(
        tenant_id=TENANT,
        prompt_id=spec.id,
        prompt_version=spec.version,
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content=spec.system),
            ChatMessage(role=MessageRole.USER, content=user_text),
        ],
        model=spec.model_hint,
        temperature=spec.temperature,
        skill="screening_criteria",
        input_refs={"input_hash": input_hash, "vacancy_title": "Backend Dev"},
    )


_VALID_SCREENING_JSON = json.dumps(
    {
        "summary": "Middle Python developer with FastAPI experience",
        "groups": [
            {
                "category": "hard_skill",
                "weight": 60.0,
                "criteria": [
                    {
                        "name": "Python",
                        "description": "3+ years Python experience",
                        "category": "hard_skill",
                        "weight": 30.0,
                        "verification": "Check resume for Python projects",
                        "must_have": True,
                    },
                    {
                        "name": "FastAPI",
                        "description": "Experience with FastAPI framework",
                        "category": "hard_skill",
                        "weight": 30.0,
                        "verification": "Check resume for FastAPI usage",
                        "must_have": True,
                    },
                ],
            },
            {
                "category": "experience",
                "weight": 40.0,
                "criteria": [
                    {
                        "name": "Backend experience",
                        "description": "3+ years backend development",
                        "category": "experience",
                        "weight": 40.0,
                        "verification": "Check work history duration",
                        "must_have": False,
                    }
                ],
            },
        ],
        "scoring_logic": "Weighted sum of criteria scores",
        "reasoning": "Criteria based on role requirements",
    }
)


# ---------------------------------------------------------------------------
# LiteLLMGateway: complete()
# ---------------------------------------------------------------------------


class TestLiteLLMGatewayComplete:
    """Тесты text completion через LiteLLMGateway."""

    @pytest.mark.asyncio
    async def test_complete_returns_content_and_provenance(self) -> None:
        from ats.infra.ai.litellm_gateway import LiteLLMGateway
        from ats.infra.stubs import InMemoryProvenanceLedger

        provenance = InMemoryProvenanceLedger()
        gateway = LiteLLMGateway(provenance)

        request = AIRequest(
            tenant_id=TENANT,
            prompt_id="test",
            prompt_version="1.0.0",
            messages=[ChatMessage(role=MessageRole.USER, content="Hello")],
            model="openai/gpt-4o-mini",
            temperature=0.0,
            skill="test",
            input_refs={"input_hash": "abc123"},
        )

        with patch(
            "ats.infra.ai.litellm_gateway.litellm.acompletion", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = _mock_completion_response("Hello! How can I help?")
            response = await gateway.complete(request)

        assert response.content == "Hello! How can I help?"
        assert response.model == "openai/gpt-4o-mini"
        assert response.usage.tokens_in == 100
        assert response.usage.tokens_out == 50
        assert response.usage.cost_usd == 0.001

        # Провенанс должен быть записан
        record = await provenance.get(TENANT, response.provenance_id)
        assert record is not None
        assert record.skill == "test"
        assert record.prompt_id == "test"
        assert record.raw_output == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_complete_non_ai_fallback_on_failure(self) -> None:
        from ats.infra.ai.litellm_gateway import LiteLLMGateway
        from ats.infra.stubs import InMemoryProvenanceLedger

        provenance = InMemoryProvenanceLedger()
        gateway = LiteLLMGateway(provenance)

        request = AIRequest(
            tenant_id=TENANT,
            prompt_id="test",
            prompt_version="1.0.0",
            messages=[ChatMessage(role=MessageRole.USER, content="Hello")],
            model="openai/gpt-4o-mini",
            temperature=0.0,
            skill="test",
        )

        with patch(
            "ats.infra.ai.litellm_gateway.litellm.acompletion", new_callable=AsyncMock
        ) as mock_call:
            mock_call.side_effect = Exception("Connection refused")
            response = await gateway.complete(request)

        # Graceful degradation: non-AI fallback
        assert response.model == "non-ai-fallback"
        assert response.confidence == 0.0


# ---------------------------------------------------------------------------
# LiteLLMGateway: structured()
# ---------------------------------------------------------------------------


class TestLiteLLMGatewayStructured:
    """Тесты structured output через LiteLLMGateway."""

    @pytest.mark.asyncio
    async def test_structured_returns_parsed_schema(self) -> None:
        from ats.infra.ai.litellm_gateway import LiteLLMGateway
        from ats.infra.stubs import InMemoryProvenanceLedger

        provenance = InMemoryProvenanceLedger()
        gateway = LiteLLMGateway(provenance)
        request = _make_ai_request()

        with patch(
            "ats.infra.ai.litellm_gateway.litellm.acompletion", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = _mock_completion_response(_VALID_SCREENING_JSON)
            response = await gateway.structured(request, ScreeningCriteriaOutput)

        assert isinstance(response.parsed, ScreeningCriteriaOutput)
        assert "Python" in response.parsed.summary
        assert len(response.parsed.groups) == 2
        assert response.repaired is False
        assert response.usage.tokens_in == 100

    @pytest.mark.asyncio
    async def test_structured_repairs_markdown_fenced_json(self) -> None:
        from ats.infra.ai.litellm_gateway import LiteLLMGateway
        from ats.infra.stubs import InMemoryProvenanceLedger

        provenance = InMemoryProvenanceLedger()
        gateway = LiteLLMGateway(provenance)
        request = _make_ai_request()

        # JSON обёрнут в markdown fence + trailing comma → должен быть отремонтирован
        broken_json = f"```json\n{_VALID_SCREENING_JSON[:-1]},}}\n```"

        with patch(
            "ats.infra.ai.litellm_gateway.litellm.acompletion", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = _mock_completion_response(broken_json)
            response = await gateway.structured(request, ScreeningCriteriaOutput)

        assert isinstance(response.parsed, ScreeningCriteriaOutput)
        assert response.repaired is True


# ---------------------------------------------------------------------------
# LiteLLMGateway: embed()
# ---------------------------------------------------------------------------


class TestLiteLLMGatewayEmbed:
    """Тесты эмбеддингов через LiteLLMGateway."""

    @pytest.mark.asyncio
    async def test_embed_returns_vector_truncated_to_pgvector_dim(self) -> None:
        from ats.infra.ai.litellm_gateway import LiteLLMGateway
        from ats.infra.stubs import InMemoryProvenanceLedger

        provenance = InMemoryProvenanceLedger()
        gateway = LiteLLMGateway(provenance)

        # Mock возвращает вектор 4096 размерности
        fake_embedding = [0.01] * 4096

        with patch(
            "ats.infra.ai.litellm_gateway.litellm.aembedding", new_callable=AsyncMock
        ) as mock_embed:
            mock_embed.return_value = {"data": [{"embedding": fake_embedding}]}

            result = await gateway.embed(TENANT, "test text for embedding")

        # Должен быть обрезан до pgvector_index_dim (4000)
        from ats.infra.ai.settings import settings as ai_settings

        assert len(result) == ai_settings.pgvector_index_dim
        assert len(result) == 4000

    @pytest.mark.asyncio
    async def test_embed_truncates_long_text(self) -> None:
        from ats.infra.ai.litellm_gateway import _truncate_for_embedding

        long_text = "x" * 100000
        truncated = _truncate_for_embedding(long_text, 8000)
        # max_chars = 8000 * 4 = 32000
        assert len(truncated) == 32000


# ---------------------------------------------------------------------------
# RedisCacheStore
# ---------------------------------------------------------------------------


class TestRedisCacheStore:
    """Тесты Redis-кэша (с mock Redis)."""

    @pytest.mark.asyncio
    async def test_cache_get_returns_none_when_redis_unavailable(self) -> None:
        cache = RedisCacheStore()
        # Redis не установлен в тестах → noop → None
        result = await cache.get("ai:cache:test")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_is_noop_when_redis_unavailable(self) -> None:
        cache = RedisCacheStore()
        # Не должен падать
        await cache.set("ai:cache:test", "value", 3600)

    @pytest.mark.asyncio
    async def test_cache_delete_is_noop_when_redis_unavailable(self) -> None:
        cache = RedisCacheStore()
        await cache.delete("ai:cache:test")

    def test_cache_key_is_deterministic(self) -> None:
        key1 = cache_key("screening_criteria", "1.0.0", "openai/gpt-4o-mini", "abc123", 0.0)
        key2 = cache_key("screening_criteria", "1.0.0", "openai/gpt-4o-mini", "abc123", 0.0)
        assert key1 == key2
        assert key1.startswith("ai:cache:")

    def test_cache_key_differs_by_model(self) -> None:
        key1 = cache_key("screening_criteria", "1.0.0", "openai/gpt-4o-mini", "abc123", 0.0)
        key2 = cache_key("screening_criteria", "1.0.0", "openai/gpt-4o", "abc123", 0.0)
        assert key1 != key2

    def test_cache_key_differs_by_temperature(self) -> None:
        key1 = cache_key("screening_criteria", "1.0.0", "openai/gpt-4o-mini", "abc123", 0.0)
        key2 = cache_key("screening_criteria", "1.0.0", "openai/gpt-4o-mini", "abc123", 0.7)
        assert key1 != key2


# ---------------------------------------------------------------------------
# AI API endpoints
# ---------------------------------------------------------------------------


class TestAIApiStatus:
    """Тесты /ai/status endpoint."""

    def test_status_returns_gateway_info(self) -> None:
        resp = client.get("/api/v1/ai/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "stub_mode" in data
        assert "default_model" in data
        assert "embedding_model" in data
        assert "embedding_dimension" in data
        assert data["embedding_dimension"] == 4096
        assert data["pgvector_index_dim"] == 4000
        assert "cache_enabled" in data
        assert "max_retries" in data

    def test_status_stub_mode_in_test_env(self) -> None:
        resp = client.get("/api/v1/ai/status")
        data = resp.json()
        # В тестах ATS_STUB_MODE по умолчанию "1"
        assert data["stub_mode"] is True
        assert data["provider"] == "stub"


class TestAIApiModels:
    """Тесты /ai/models endpoint."""

    def test_models_returns_default_and_embedding(self) -> None:
        resp = client.get("/api/v1/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        roles = [m["role"] for m in data["models"]]
        assert "default" in roles
        assert "embedding" in roles
        assert len(data["models"]) >= 2


class TestAIApiProvenance:
    """Тесты /ai/provenance endpoints (whitebox AI)."""

    def test_get_provenance_not_found(self) -> None:
        resp = client.get(f"/api/v1/ai/provenance/{uuid4()}")
        assert resp.status_code == 404

    def test_get_provenance_existing_record(self) -> None:
        container = get_container()
        record = ProvenanceRecord.create(
            tenant_id=TENANT,
            skill="screening_criteria",
            prompt_id="screening_criteria",
            prompt_version="1.0.0",
            model="openai/gpt-4o-mini",
            input_hash="abc123",
            input_refs={"vacancy_title": "Backend Dev"},
            raw_output='{"summary": "test"}',
            parsed_output='{"summary": "test"}',
            confidence=0.95,
            latency_ms=1200,
            tokens_in=150,
            tokens_out=80,
            cost_usd=0.002,
        )
        asyncio.run(container.provenance_ledger.append(record))

        resp = client.get(f"/api/v1/ai/provenance/{record.provenance_id.value}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill"] == "screening_criteria"
        assert data["prompt_id"] == "screening_criteria"
        assert data["model"] == "openai/gpt-4o-mini"
        assert data["confidence"] == 0.95
        assert data["human_verified"] is False
        assert data["input_refs"]["vacancy_title"] == "Backend Dev"

    def test_mark_provenance_verified(self) -> None:
        container = get_container()
        record = ProvenanceRecord.create(
            tenant_id=TENANT,
            skill="parse_resume",
            prompt_id="parse_resume",
            prompt_version="1.0.0",
            model="openai/gpt-4o-mini",
            input_hash="def456",
            input_refs={},
            raw_output="parsed text",
            parsed_output="parsed text",
            confidence=None,
            latency_ms=500,
            tokens_in=100,
            tokens_out=200,
            cost_usd=0.001,
        )
        asyncio.run(container.provenance_ledger.append(record))

        resp = client.post(f"/api/v1/ai/provenance/{record.provenance_id.value}/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["human_verified"] is True

    def test_verify_provenance_not_found(self) -> None:
        resp = client.post(f"/api/v1/ai/provenance/{uuid4()}/verify")
        assert resp.status_code == 404
