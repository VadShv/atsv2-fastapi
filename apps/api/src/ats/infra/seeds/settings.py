"""Настройки сида демо-данных.

Контролирует количество генерируемых сущностей и seed для воспроизводимости.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATS_SEED_", env_file=".env", extra="ignore")

    # Seed для воспроизводимости (детерминированный генератор)
    random_seed: int = Field(
        default=42,
        description="Seed для генератора (детерминированный сид)",
    )

    # Количество тенантов
    tenant_count: int = Field(
        default=3,
        description="Количество демо-тенантов",
    )

    # Количество кандидатов на тенант
    candidates_per_tenant: int = Field(
        default=5000,
        description="Кандидатов на тенант (5000 по умолчанию)",
    )

    # Количество вакансий на тенант
    vacancies_per_tenant: int = Field(
        default=20,
        description="Вакансий на тенант (20 по умолчанию)",
    )

    # Вероятность что кандидат подал отклик (0.0-1.0)
    application_probability: float = Field(
        default=0.35,
        description="Вероятность отклика кандидата на вакансию",
    )

    # Максимальное количество откликов от одного кандидата
    max_applications_per_candidate: int = Field(
        default=3,
        description="Макс. откликов от одного кандидата",
    )

    # Дропать ли данные перед сидом
    truncate_before: bool = Field(
        default=True,
        description="Очистить таблицы перед сидом (True) или добавить к существующим",
    )


settings = SeedSettings()
