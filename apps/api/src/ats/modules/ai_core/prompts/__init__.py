"""Регистрация промптов при импорте.

Импорт этого модуля гарантирует, что все промпты зарегистрированы в REGISTRY.
"""

from ats.modules.ai_core.prompts.registry import (
    OutputFormat,
    PromptSpec,
    register,
)

# screening_criteria v1.0.0 — генерация критериев скрининга из описания роли
SCREENING_CRITERIA_V1 = register(
    PromptSpec(
        id="screening_criteria",
        version="1.0.0",
        name="Generate Screening Criteria",
        description="Генерирует критерии скрининга кандидатов из описания роли вакансии",
        system=(
            "Ты — Senior Recruiter и эксперт по оценке персонала. "
            "Ты строишь объективные, проверяемые критерии скрининга. "
            "Отвечай СТРОГО на русском языке в формате JSON по схеме."
        ),
        template_file="screening_criteria_v1.txt",
        output_format=OutputFormat.JSON,
        model_hint="gpt-4o-mini",
        temperature=0.0,
        output_schema="ScreeningCriteriaOutput",
        variables=[
            "role_description",
            "vacancy_title",
            "seniority",
            "team",
        ],
    )
)

# parse_resume v1.0.0 — парсинг резюме в структурированную карточку кандидата
PARSE_RESUME_V1 = register(
    PromptSpec(
        id="parse_resume",
        version="1.0.0",
        name="Parse Resume",
        description="Извлекает структурированный профиль кандидата из текста резюме",
        system=(
            "Ты — HR-аналитик и эксперт по парсингу резюме. "
            "Извлекаешь структурированные данные из сырого текста. "
            "Отвечай СТРОГО на русском языке в формате JSON по схеме."
        ),
        template_file="parse_resume_v1.txt",
        output_format=OutputFormat.JSON,
        model_hint="gpt-4o-mini",
        temperature=0.0,
        output_schema="ParsedResume",
        variables=["resume_text"],
    )
)
