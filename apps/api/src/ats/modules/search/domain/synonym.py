"""Домен синонимов поиска (JUGO-172).

Словарь синонимов расширяет поисковые запросы: термин → терм + синонимы.
Например: «python» → python | py | python3.

Мульти-тенант: каждый тенант имеет свой набор синонимов.
SECURE FIRST: RLS на уровне БД.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class SynonymEntry(BaseModel):
    """Запись словаря синонимов: term → synonyms[]."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    term: str = Field(min_length=1, max_length=255)
    synonyms: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("term")
    @classmethod
    def _normalize_term(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Термин не может быть пустым")
        return v

    @field_validator("synonyms")
    @classmethod
    def _normalize_synonyms(cls, v: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for s in v:
            s = s.strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                result.append(s)
        return result

    def to_map_entry(self) -> tuple[str, list[str]]:
        """Получить пару (term_lower, synonyms) для карты расширения запросов."""
        return self.term.lower(), [s.lower() for s in self.synonyms]
