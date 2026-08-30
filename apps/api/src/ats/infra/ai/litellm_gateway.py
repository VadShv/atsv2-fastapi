"""Реализация AIGateway на LiteLLM.

Единая точка входа ко всем LLM: роутинг, retry/fallback, семантический кэш,
метрики, бюджеты, запись провенанса. Домен зависит от абстракции, не от этой реализации.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TypeVar

import litellm
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ats.infra.ai.cache import CacheStore, cache_key
from ats.infra.ai.json_repair import parse_structured
from ats.infra.ai.settings import settings as ai_settings
from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.domain.models import (
    AIChunk,
    AIRequest,
    AIResponse,
    AIUsage,
    ProvenanceRecord,
    StructuredResponse,
)
from ats.modules.ai_core.ports.provenance import ProvenanceLedger
from ats.shared.ids import ProvenanceId

logger = logging.getLogger(__name__)
T = TypeVar("T")

# LiteLLM может логировать шумно — приглушим
litellm.suppress_debug_info = True


class LiteLLMGateway(AIGateway):
    """Production-реализация AIGateway через LiteLLM.

    Особенности:
    - Retry с экспоненциальным backoff (устойчивость)
    - Fallback на резервную модель (устойчивость)
    - Семантический кэш для temperature==0 (скорость/стоимость)
    - Запись провенанса для каждого вызова (whitebox)
    - Бюджеты токенов на запрос (runaway protection)
    - Провайдер: Cloud.ru (OpenAI-совместимый api_base + api_key из env)
    """

    def __init__(
        self,
        provenance: ProvenanceLedger,
        cache: CacheStore | None = None,
    ) -> None:
        self._provenance = provenance
        self._cache = cache

    @property
    def dimension(self) -> int:
        return ai_settings.embedding_dimension

    def _provider_kwargs(self) -> dict[str, str]:
        """Cloud.ru OpenAI-совместимый роутинг: api_base + api_key.

        SECURE FIRST: ключи только из env (ai_settings), никогда из кода.
        Возвращает пустой dict если cloudru_api_key не задан — тогда LiteLLM
        использует стандартный env-роутинг (OPENAI_API_KEY и т.д.).
        """
        if ai_settings.cloudru_api_key:
            return {
                "api_base": ai_settings.cloudru_api_base,
                "api_key": ai_settings.cloudru_api_key,
            }
        return {}

    async def embed(self, tenant_id, text: str) -> list[float]:  # type: ignore[no-untyped-def]
        """Эмбеддинг текста через LiteLLM (для семантического поиска).

        Провайдер: Cloud.ru (OpenAI-совместимый api_base + api_key из env).
        Текст обрезается по embedding_max_tokens для защиты от превышения лимита.
        Эмбеддинг обрезается до pgvector_index_dim (4096→4000, лимит pgvector HNSW).
        """
        truncated = _truncate_for_embedding(text, ai_settings.embedding_max_tokens)
        kwargs: dict[str, object] = {
            "model": ai_settings.embedding_model,
            "input": truncated,
            "timeout": ai_settings.timeout_seconds,
        }
        kwargs.update(self._provider_kwargs())
        response = await litellm.aembedding(**kwargs)
        embedding = list(response["data"][0]["embedding"])
        # Контроль размерности (SECURE FIRST / устойчивость)
        if len(embedding) != ai_settings.embedding_dimension:
            logger.warning(
                "Embedding dimension mismatch: got %d, expected %d",
                len(embedding),
                ai_settings.embedding_dimension,
            )
        # Обрезка до pgvector_index_dim (pgvector HNSW лимит на halfvec = 4000)
        index_dim = ai_settings.pgvector_index_dim
        if len(embedding) > index_dim:
            logger.debug(
                "Truncating embedding %d → %d for pgvector index",
                len(embedding),
                index_dim,
            )
            embedding = embedding[:index_dim]
        return embedding

    async def complete(self, request: AIRequest) -> AIResponse:
        model = request.model or ai_settings.default_model
        # Кэш только для детерминированных вызовов
        if self._cache is not None and request.temperature == 0:
            # input_hash считается в PromptSpec.render, сюда приходит уже готовый
            cached = await self._try_cache(request, model)
            if cached is not None:
                return cached

        response = await self._call_with_retry(request, model)
        return response

    async def stream(self, request: AIRequest) -> AsyncIterator[AIChunk]:
        model = request.model or ai_settings.default_model
        provenance_id = ProvenanceId.generate()
        collected: list[str] = []

        try:
            stream = await self._raw_stream(request, model)
            async for chunk in stream:
                delta = chunk["choices"][0]["delta"].get("content", "") or ""
                if delta:
                    collected.append(delta)
                    yield AIChunk(delta=delta, provenance_id=provenance_id)
        finally:
            # Записываем провенанс стрима (best-effort)
            await self._record_provenance(
                request=request,
                model=model,
                raw_output="".join(collected),
                parsed_output="".join(collected),
                usage=AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0),
                latency_ms=0,
                confidence=None,
                provenance_id=provenance_id,
            )

    async def structured(self, request: AIRequest, schema: type[T]) -> StructuredResponse[T]:
        model = request.model or ai_settings.default_model

        # Кэш structured-вызовов
        if self._cache is not None and request.temperature == 0:
            cached = await self._try_structured_cache(request, model, schema)
            if cached is not None:
                return cached

        import time

        start = time.monotonic()
        response = await self._call_with_retry(request, model)
        latency_ms = int((time.monotonic() - start) * 1000)

        # Парсинг с ремонтом (устойчивость/whitebox)
        parsed, _cleaned, repaired = parse_structured(response.raw_output, schema)
        # Fallback: попробовать fallback-модель
        if parsed is None and (ai_settings.fallback_model and model != ai_settings.fallback_model):
            logger.warning(
                "JSON parse failed on %s, retrying with fallback %s",
                model,
                ai_settings.fallback_model,
            )
            request = _with_model(request, ai_settings.fallback_model)
            response = await self._call_with_retry(request, ai_settings.fallback_model)
            parsed, _cleaned, repaired = parse_structured(response.raw_output, schema)

        if parsed is None:
            raise AIOutputError(f"Failed to parse structured output for prompt={request.prompt_id}")

        return StructuredResponse(
            provenance_id=response.provenance_id,
            parsed=parsed,
            raw_output=response.raw_output,
            model=response.model,
            usage=response.usage,
            latency_ms=latency_ms,
            confidence=response.confidence,
            repaired=repaired,
        )

    # --- internals ---

    async def _call_with_retry(self, request: AIRequest, model: str) -> AIResponse:
        @retry(
            retry=retry_if_exception_type(
                (litellm.APIConnectionError, litellm.RateLimitError, TimeoutError)
            ),
            stop=stop_after_attempt(ai_settings.max_retries),
            wait=wait_exponential(multiplier=ai_settings.retry_base_delay, max=10.0),
            reraise=True,
        )
        async def _call() -> AIResponse:
            return await self._raw_complete(request, model)

        try:
            return await _call()
        except Exception as exc:
            logger.error("LLM call failed for %s: %s", request.prompt_id, exc)
            # Fallback на non-AI режим (graceful degradation)
            if ai_settings.enable_non_ai_fallback:
                return self._non_ai_fallback(request, model, exc)
            raise

    async def _raw_complete(self, request: AIRequest, model: str) -> AIResponse:
        import time

        start = time.monotonic()
        messages = [{"role": m.role.value, "content": m.content} for m in request.messages]
        # LiteLLM: единый интерфейс к OpenAI/Anthropic/Yandex и др.
        # Cloud.ru: OpenAI-совместимый роутинг через api_base + api_key
        resp = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=min(
                request.max_tokens or ai_settings.max_tokens_per_request,
                ai_settings.max_tokens_per_request,
            ),
            timeout=ai_settings.timeout_seconds,
            **self._provider_kwargs(),
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = AIUsage(
            tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
            tokens_out=resp.usage.completion_tokens if resp.usage else 0,
            cost_usd=float(resp._hidden_params.get("response_cost", 0.0) or 0.0),
        )
        provenance_id = await self._record_provenance(
            request=request,
            model=model,
            raw_output=content,
            parsed_output=content,
            usage=usage,
            latency_ms=latency_ms,
            confidence=None,
        )
        return AIResponse(
            provenance_id=provenance_id,
            content=content,
            raw_output=content,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
        )

    async def _raw_stream(self, request: AIRequest, model: str):
        messages = [{"role": m.role.value, "content": m.content} for m in request.messages]
        return await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=min(
                request.max_tokens or ai_settings.max_tokens_per_request,
                ai_settings.max_tokens_per_request,
            ),
            timeout=ai_settings.timeout_seconds,
            stream=True,
            **self._provider_kwargs(),
        )

    async def _try_cache(self, request: AIRequest, model: str) -> AIResponse | None:
        assert self._cache is not None
        key = self._cache_key(request, model)
        cached_raw = await self._cache.get(key)
        if cached_raw is None:
            return None
        # Восстанавливаем из кэша (без нового вызова LLM)
        import json

        data = json.loads(cached_raw)
        return AIResponse(
            provenance_id=ProvenanceId.from_string(data["provenance_id"]),
            content=data["content"],
            raw_output=data["content"],
            model=model,
            usage=AIUsage(**data["usage"]),
            latency_ms=0,
        )

    async def _try_structured_cache(
        self, request: AIRequest, model: str, schema: type[T]
    ) -> StructuredResponse[T] | None:
        assert self._cache is not None
        key = self._cache_key(request, model)
        cached_raw = await self._cache.get(key)
        if cached_raw is None:
            return None
        parsed, _, _ = parse_structured(cached_raw, schema)
        if parsed is None:
            return None
        return StructuredResponse(
            provenance_id=ProvenanceId.generate(),
            parsed=parsed,
            raw_output=cached_raw,
            model=model,
            usage=AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0),
            latency_ms=0,
            repaired=False,
        )

    def _cache_key(self, request: AIRequest, model: str) -> str:
        # input_hash вычисляется в PromptSpec.render и передаётся в input_refs
        input_hash = request.input_refs.get("input_hash", "")
        return cache_key(
            request.prompt_id,
            request.prompt_version,
            model,
            input_hash,
            request.temperature,
        )

    async def _record_provenance(
        self,
        *,
        request: AIRequest,
        model: str,
        raw_output: str,
        parsed_output: str,
        usage: AIUsage,
        latency_ms: int,
        confidence: float | None,
        provenance_id: ProvenanceId | None = None,
    ) -> ProvenanceId:
        record = ProvenanceRecord(
            provenance_id=provenance_id or ProvenanceId.generate(),
            tenant_id=request.tenant_id,
            skill=request.skill,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            model=model,
            input_hash=request.input_refs.get("input_hash", ""),
            input_refs=request.input_refs,
            raw_output=raw_output,
            parsed_output=parsed_output,
            confidence=confidence,
            latency_ms=latency_ms,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_usd=usage.cost_usd,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            human_verified=False,
            reasoning_trace="",
            non_ai=False,
        )
        await self._provenance.append(record)
        return record.provenance_id

    def _non_ai_fallback(self, request: AIRequest, model: str, exc: Exception) -> AIResponse:
        """Graceful degradation: LLM недоступен — возвращаем заглушку с пометкой non_ai.

        Конкретные скиллы могут переопределять fallback-логику.
        Здесь — минимальная заглушка, чтобы не падать.
        """
        logger.warning("Using non-AI fallback for %s: %s", request.prompt_id, exc)
        return AIResponse(
            provenance_id=ProvenanceId.generate(),
            content="",
            raw_output="",
            model="non-ai-fallback",
            usage=AIUsage(tokens_in=0, tokens_out=0, cost_usd=0.0),
            latency_ms=0,
            confidence=0.0,
        )


def _with_model(request: AIRequest, model: str) -> AIRequest:
    """Создать копию запроса с другой моделью (immutable dataclass)."""
    from dataclasses import replace

    return replace(request, model=model)


def _truncate_for_embedding(text: str, max_tokens: int) -> str:
    """Грубая обрезка текста до max_tokens (приблизительно chars/4).

    Защита от превышения лимита токенов эмбеддинг-модели (устойчивость).
    Точная токенизация не требуется — обрезаем с запасом.
    """
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


class AIOutputError(Exception):
    """Не удалось распарсить structured output."""
