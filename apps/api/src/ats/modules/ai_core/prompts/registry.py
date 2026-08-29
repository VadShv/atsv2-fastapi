"""Промпт-реестр: промпты как код.

Каждый промпт — версионная Pydantic-модель. Версия фиксируется в provenance (whitebox).
Сами шаблоны живут рядом как .txt/.md, здесь — только метаданные и загрузка.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

PROMPTS_DIR = Path(__file__).parent


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


class PromptSpec(BaseModel):
    """Спецификация промпта: метаданные + ссылка на шаблон."""

    id: str = Field(description="Стабильный идентификатор, напр. screening_criteria")
    version: str = Field(description="Семвер, напр. 1.0.0")
    name: str
    description: str
    system: str = Field(description="Системный промпт")
    template_file: str = Field(description="Имя файла шаблона в prompts/")
    output_format: OutputFormat = OutputFormat.JSON
    model_hint: str | None = Field(
        default=None, description="Рекомендуемая модель (можно переопределить роутером)"
    )
    temperature: float = Field(default=0.0, description="0 для детерминизма")
    # Pydantic-схема для structured output (имя класса-модели, резолвится в runtime)
    output_schema: str | None = Field(default=None)
    variables: list[str] = Field(
        default_factory=list, description="Имена переменных шаблона"
    )

    def load_template(self) -> str:
        return (PROMPTS_DIR / self.template_file).read_text(encoding="utf-8")

    def render(self, variables: dict[str, str]) -> tuple[str, str]:
        """Рендер шаблона переменными. Возвращает (user_message, input_hash)."""
        template = self.load_template()
        rendered = template
        for key in self.variables:
            placeholder = "{{" + key + "}}"
            if placeholder in rendered:
                rendered = rendered.replace(placeholder, variables.get(key, ""))
        # Хэш входа для провенанса (воспроизводимость)
        input_hash = hashlib.sha256(
            (self.system + rendered).encode("utf-8")
        ).hexdigest()
        return rendered, input_hash


# Реестр всех промптов. Новые промпты регистрируются здесь.
REGISTRY: dict[str, PromptSpec] = {}


def register(spec: PromptSpec) -> PromptSpec:
    key = f"{spec.id}:v{spec.version}"
    REGISTRY[key] = spec
    return spec


def get_prompt(prompt_id: str, version: str) -> PromptSpec:
    key = f"{prompt_id}:v{version}"
    spec = REGISTRY.get(key)
    if spec is None:
        raise KeyError(f"Prompt not found: {key}")
    return spec


def hash_input(system: str, user: str) -> str:
    return hashlib.sha256((system + user).encode("utf-8")).hexdigest()
