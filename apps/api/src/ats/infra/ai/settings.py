"""Конфигурация AI Gateway (secure-first: ключи только из env).

Провайдер по умолчанию — Cloud.ru (OpenAI-совместимый API).
Эмбеддинги — 4096 (фиксированное решение проекта).
Ключи и base_url НИКОГДА не в коде, только из env.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATS_AI_", env_file=".env", extra="ignore"
    )

    # --- Провайдер: Cloud.ru (OpenAI-совместимый) ---
    # base_url Cloud.ru (например https://llm.api.cloud.ru/v1)
    cloudru_api_base: str = Field(
        default="https://llm.api.cloud.ru/v1",
        description="Cloud.ru LLM API base URL (OpenAI-совместимый)",
    )
    cloudru_api_key: str = Field(default="", description="Cloud.ru API key (из env)")
    # Модели Cloud.ru (префикс openai/ для LiteLLM → OpenAI-совместимый роутинг)
    default_model: str = "openai/gpt-4o-mini"
    fallback_model: str | None = "openai/gpt-4o-mini"

    # --- Legacy OpenAI (если нужен fallback на другой провайдер) ---
    openai_api_key: str = Field(default="", description="OpenAI API key (опционально)")

    # --- Эмбеддинги (4096 — фиксированное решение проекта) ---
    embedding_model: str = "openai/text-embedding-3-large"
    embedding_dimension: int = 4096
    # Максимальная длина текста для эмбеддинга (токены, защита от превышения лимита)
    embedding_max_tokens: int = 8000

    # --- Семантический кэш (Redis) ---
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86400

    # --- Retry/fallback (устойчивость) ---
    max_retries: int = 3
    retry_base_delay: float = 0.5
    timeout_seconds: float = 30.0

    # --- Бюджеты (runaway protection) ---
    max_tokens_per_request: int = 4096

    # --- Fallback ---
    enable_non_ai_fallback: bool = True


settings = AISettings()
