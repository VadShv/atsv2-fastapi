"""Схема structured output для AI-скоринга скрининга (JUGO-404).

Используется AIGateway.structured() для получения оценки по каждому критерию.
Шкала: 0 / 0.5 / 1 (дискретная). Каждая оценка содержит цитату и объяснение.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CriterionEvaluationOutput(BaseModel):
    """Оценка одного критерия: 0 / 0.5 / 1."""

    criterion_name: str = Field(description="Название критерия")
    category: str = Field(description="Категория: hard_skill, soft_skill, experience, etc.")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Оценка: 0 (fail) / 0.5 (partial) / 1 (pass)",
    )
    weight: float = Field(ge=0, le=100, description="Вес критерия")
    evidence: str = Field(description="Цитата из резюме, подтверждающая оценку")
    explanation: str = Field(description="Почему такая оценка (whitebox)")
    must_have: bool = Field(default=False, description="Обязательный критерий")

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        """Только 0 / 0.5 / 1 допускаются (дискретная шкала)."""
        allowed = {0.0, 0.5, 1.0}
        if v not in allowed:
            # Округляем к ближайшему допустимому (устойчивость к выходу LLM за шкалу)
            nearest = min(allowed, key=lambda a: abs(a - v))
            return nearest
        return v


class ScreeningScoreOutput(BaseModel):
    """Полный результат AI-скоринга кандидата по критериям."""

    summary: str = Field(description="Краткое саммари оценки кандидата")
    evaluations: list[CriterionEvaluationOutput] = Field(
        min_length=1, description="Оценка по каждому критерию"
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Уверенность модели в оценке",
    )
