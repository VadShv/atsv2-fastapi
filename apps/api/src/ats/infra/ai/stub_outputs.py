"""Stub-выводы AI-скиллов (запуск без реальной LLM).

Реалистичные предзаготовленные structured outputs для dev/тестов.
Каждая функция возвращает JSON-строку, валидную по схеме скилла.
"""

from __future__ import annotations

import hashlib
import json
import math


def stub_screening_criteria() -> str:
    """Реалистичный stub ScreeningCriteriaOutput."""
    return json.dumps(
        {
            "summary": (
                "Идеальный кандидат — middle Python-разработчик с опытом FastAPI и PostgreSQL."
            ),
            "groups": [
                {
                    "category": "hard_skill",
                    "weight": 40,
                    "criteria": [
                        {
                            "name": "Python",
                            "description": "Опыт работы с Python 3.10+ от 2 лет",
                            "category": "hard_skill",
                            "weight": 20,
                            "verification": "Проверить по резюме: проекты, длительность",
                            "must_have": True,
                        },
                        {
                            "name": "FastAPI",
                            "description": "Опыт разработки REST API на FastAPI",
                            "category": "hard_skill",
                            "weight": 20,
                            "verification": "Проекты в резюме, техническое интервью",
                            "must_have": True,
                        },
                    ],
                },
                {
                    "category": "experience",
                    "weight": 30,
                    "criteria": [
                        {
                            "name": "Коммерческий опыт",
                            "description": "От 2 лет коммерческой разработки",
                            "category": "experience",
                            "weight": 30,
                            "verification": "Трудовая/рекомендации, таймлайн резюме",
                            "must_have": True,
                        }
                    ],
                },
                {
                    "category": "soft_skill",
                    "weight": 20,
                    "criteria": [
                        {
                            "name": "Коммуникация",
                            "description": "Чёткая письменная и устная коммуникация",
                            "category": "soft_skill",
                            "weight": 20,
                            "verification": "Поведенческое интервью, SCRUM-ритуалы",
                            "must_have": False,
                        }
                    ],
                },
                {
                    "category": "red_flag",
                    "weight": 10,
                    "criteria": [
                        {
                            "name": "Частая смена работы",
                            "description": "Более 3 мест работы за последний год",
                            "category": "red_flag",
                            "weight": 10,
                            "verification": "Анализ таймлайна резюме",
                            "must_have": False,
                        }
                    ],
                },
            ],
            "scoring_logic": (
                "Финальный балл = взвешенная сумма по критериям; any must_have fail → reject."
            ),
            "reasoning": (
                "Критерии выведены из описания роли: ключевые hard skills "
                "взяты из требований, опыт и red flags добавлены "
                "для качества скрининга."
            ),
        },
        ensure_ascii=False,
    )


def stub_parsed_resume() -> str:
    """Реалистичный stub ParsedResume для dev/тестов."""
    return json.dumps(
        {
            "full_name": "Иванов Иван Иванович",
            "headline": "Middle Python Developer",
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Git"],
            "experience": [
                {
                    "company": "ООО ТехКомпани",
                    "position": "Python Developer",
                    "start_date": "2022-03",
                    "end_date": "2026-01",
                    "description": "Разработка backend-сервисов на FastAPI, проектирование API.",
                },
                {
                    "company": "Стартап XYZ",
                    "position": "Junior Developer",
                    "start_date": "2020-06",
                    "end_date": "2022-02",
                    "description": "Поддержка и доработка Django-приложений.",
                },
            ],
            "education": [
                {
                    "institution": "МГТУ им. Баумана",
                    "degree": "Магистр, Прикладная информатика",
                    "start_date": "2016",
                    "end_date": "2022",
                }
            ],
            "total_years": 5.5,
            "summary": (
                "Python-разработчик с 5+ годами опыта. "
                "Специализируется на backend-разработке (FastAPI, PostgreSQL)."
            ),
            "searchable_text": (
                "Middle Python Developer. Python, FastAPI, PostgreSQL, Docker, Git. "
                "Разработка backend-сервисов, проектирование API, Django."
            ),
            "red_flags": [],
        },
        ensure_ascii=False,
    )


def stub_embed(text: str, dimension: int = 1536) -> list[float]:
    """Детерминированный pseudo-эмбеддинг для dev/тестов.

    Bag-of-words на хэше слов: слова, общие для запроса и документа,
    дают ненулевую косинусную схожесть. Нормализованный вектор.
    Детерминизм: одинаковый текст → одинаковый вектор.
    """
    vec = [0.0] * dimension
    for word in text.lower().split():
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        vec[h % dimension] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# Диспетчер: prompt_id → stub JSON
STUB_OUTPUTS: dict[str, callable[[], str]] = {
    "screening_criteria": stub_screening_criteria,
    "parse_resume": stub_parsed_resume,
}
