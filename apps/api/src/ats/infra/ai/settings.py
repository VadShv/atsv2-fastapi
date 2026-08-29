"""Конфигурация AI Gateway (secure-first: ключи только из env)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATS_AI_", env_file=".env", extra="ignore"
    )

    # Провайдеры (ключи только из env, никогда в коде)
    openai_api_key: str = Field(default="", description="OpenAI API key")
    # Роутинг по умолчанию
   default_model: str = "gpt-4o-mini"
    # Эмбеддинги (для семантического поиска кандидатов)
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
   # Семантический кэш (Redis). Пусто — кэш выключен.
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86400
    # Retry/fallback (устойчивость)
    max_retries: int = 3
    retry_base_delay: float = 0.5
    timeout_seconds: float = 30.0
    # Бюджеты (runaway protection)
    max_tokens_per_request: int = 4096
    # Fallback-модель если основная недоступна
    fallback_model: str | None = "gpt-4o-mini"
    # Включить детерминированный non-AI fallback при полной недоступности LLM
    enable_non_ai_fallback: bool = True


settings = AISettings()
