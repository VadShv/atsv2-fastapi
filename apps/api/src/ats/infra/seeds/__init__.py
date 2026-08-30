"""Модуль сида демо-данных (JUGO-014).

Генератор детерминированных демо-данных для стенда интеграции:
    - 2-3 тенанта с разными ролями (мульти-тенант)
    - 5000 кандидатов на тенант
    - 20 вакансий на тенант (с описанием роли + требованиями)
    - ~5000 откликов (applications)
    - Стадии пайплайна для каждой вакансии

Запуск:
    python -m ats.infra.seeds              # стандартный сид
    python -m ats.infra.seeds --dry-run    # только сгенерировать
    python -m ats.infra.seeds --count 100  # 100 кандидатов

УСТОЙЧИВОСТЬ: Faker не обязателен — fallback на встроенные списки.
Детерминированный генератор (random.Random(seed)).
"""

from __future__ import annotations

from ats.infra.seeds.generator import (
    SeedApplication,
    SeedCandidate,
    SeedData,
    SeedGenerator,
    SeedPipelineStage,
    SeedRole,
    SeedTenant,
    SeedUser,
    SeedVacancy,
)
from ats.infra.seeds.settings import SeedSettings
from ats.infra.seeds.settings import settings as seed_settings

__all__ = [
    "SeedApplication",
    "SeedCandidate",
    "SeedData",
    "SeedGenerator",
    "SeedPipelineStage",
    "SeedRole",
    "SeedSettings",
    "SeedTenant",
    "SeedUser",
    "SeedVacancy",
    "seed_settings",
]
