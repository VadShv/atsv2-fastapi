"""Слой ремонта JSON (устойчивость/whitebox).

LLM иногда возвращают JSON с markdown-обёрткой, trailing commas, обрезанным концом.
Этот слой пытается восстановить и распарсить. Каждая попытка ремонта логируется
через repaired=True в StructuredResponse.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# Маркеры markdown-блоков кода
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
# Trailing comma перед } или ]
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def extract_json(raw: str) -> str:
    """Извлечь JSON из сырого вывода LLM."""
    text = raw.strip()

    # 1. Если весь ответ — markdown-блок
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # 2. Если есть JSON-объект/массив, но вокруг мусор — найдём границы
    if not (text.startswith("{") or text.startswith("[")):
        start = _find_first(text, ("{", "["))
        if start is not None:
            text = _extract_balanced(text, start)

    return text


def repair_json(text: str) -> str:
    """Попытаться починить типичные поломки JSON."""
    # Убираем trailing commas
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def parse_structured(raw: str, schema: type[T]) -> tuple[T | None, str, bool]:
    """Распарсить сырой вывод в Pydantic-модель.

    Возвращает (parsed_or_None, cleaned_output, repaired).
    Делает несколько попыток: as-is → extract → repair.
    """
    attempts = [
        raw,
        extract_json(raw),
        repair_json(extract_json(raw)),
    ]
    last_cleaned = raw
    for i, attempt in enumerate(attempts):
        try:
            parsed = schema.model_validate_json(attempt)
            return parsed, attempt, i > 0
        except (ValidationError, json.JSONDecodeError):
            last_cleaned = attempt
            continue
    return None, last_cleaned, True


def _find_first(text: str, chars: tuple[str, ...]) -> int | None:
    positions = [text.index(c) for c in chars if c in text]
    return min(positions) if positions else None


def _extract_balanced(text: str, start: int) -> str:
    """Извлечь сбалансированный JSON-блок начиная с позиции start."""
    open_char = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # Не сбалансировано — вернём что есть
    return text[start:]
