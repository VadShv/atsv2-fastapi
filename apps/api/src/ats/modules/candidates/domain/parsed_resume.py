"""Доменная модель распарсенного резюме.

Результат AI-парсинга резюме в структурированную карточку кандидата.
Whitebox: каждый результат ссылается на provenance.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkExperience(BaseModel):
    """Опыт работы — одна позиция."""

    company: str = ""
    position: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class Education(BaseModel):
    """Образование — одна запись."""

    institution: str = ""
    degree: str = ""
    start_date: str = ""
    end_date: str = ""


class ParsedResume(BaseModel):
    """Структурированный результат AI-парсинга резюме.

    Извлекается из сырого текста/PDF резюме. PII (email/телефон) хранятся
    отдельно в PII-vault, здесь — обезличенные поля для профиля и поиска.
    """

    full_name: str = Field(description="ФИО кандидата")
    headline: str = Field(default="", description="Должность/специализация")
    skills: list[str] = Field(default_factory=list)
    experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    total_years: float = Field(default=0.0, description="Суммарный опыт в годах")
    summary: str = Field(default="", description="Краткое саммари профиля")
    # Семантический текст для эмбеддинга/поиска (без PII)
    searchable_text: str = Field(default="")
    # Обнаруженные red flags (пробелы, частая смена работы)
    red_flags: list[str] = Field(default_factory=list)
