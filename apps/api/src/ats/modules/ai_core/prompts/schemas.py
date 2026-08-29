"""Схема structured output для генерации критериев скрининга.

Используется AIGateway.structured() для получения типобезопасного результата
и слоем «ремонта» JSON при сбое парсинга.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class CriterionCategory(str, Enum):
    HARD_SKILL = "hard_skill"
    SOFT_SKILL = "soft_skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    RED_FLAG = "red_flag"


class ScreeningCriterion(BaseModel):
    """Один критерий скрининга."""

    name: str = Field(description="Краткое название критерия")
    description: str = Field(description="Что проверяем, в измеримых терминах")
    category: CriterionCategory
    weight: float = Field(
        ge=0, le=100, description="Вес критерия, сумма по категории и в целом = 100"
    )
    # Как проверить критерий (вопросы, маркеры в резюме, тесты)
    verification: str = Field(description="Как рекрутер проверит этот критерий")
    must_have: bool = Field(
        default=False, description="Обязательный (fail = отказ на скрининге)"
    )


class CriterionGroup(BaseModel):
    """Группа критериев по категории."""

    category: CriterionCategory
    weight: float = Field(ge=0, le=100, description="Суммарный вес группы")
    criteria: list[ScreeningCriterion] = Field(min_length=1)


class ScreeningCriteriaOutput(BaseModel):
    """Полный набор ИИ-сгенерированных критериев скрининга для вакансии."""

    summary: str = Field(description="Краткое саммари профиля идеального кандидата")
    groups: list[CriterionGroup] = Field(min_length=1)
    # Общая логика скоринга: как комбинировать критерии в финальный балл
    scoring_logic: str = Field(description="Как комбинировать критерии в финальный балл")
    reasoning: str = Field(description="Почему именно эти критерии (whitebox)")

    @field_validator("groups")
    @classmethod
    def validate_weights(cls, v: list[CriterionGroup]) -> list[CriterionGroup]:
        total = sum(g.weight for g in v)
        if abs(total - 100) > 0.01:
            raise ValueError(
                f"Сумма весов групп критериев должна быть 100, получено {total}"
            )
        return v
