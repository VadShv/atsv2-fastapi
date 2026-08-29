"""Настройки логирования (SECURE FIRST: уровень из env, маскирование ПД).

Структурные JSON-логи с tenant_id/trace_id + маскирование ПД.
Уровень настраивается из env (ATS_LOG_LEVEL).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATS_LOG_", env_file=".env", extra="ignore"
    )

    level: str = Field(default="INFO", description="Уровень логирования (DEBUG/INFO/WARNING/ERROR)")
    json_format: bool = Field(
        default=True,
        description="JSON-формат (True) или человекочитаемый (False, для dev)",
    )
    mask_pii: bool = Field(
        default=True,
        description="Маскировать ПД (email, телефон, ФИО) в логах",
    )
    # Паттерны ПД для маскирования
    pii_email_pattern: str = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    pii_phone_pattern: str = r"\+?\d[\d\s\-\(\)]{7,}\d"
    # Сколько символов ФИО оставлять (остальное — ***)
    pii_name_visible_chars: int = 2


settings = LogSettings()
