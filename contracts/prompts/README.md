# contracts/prompts/ — Контракты AI-промптов

Каждый промпт — версионный контракт с явными входами/выходами (whitebox AI).

## Реестр

| Prompt ID | Version | Skill | Output Schema |
|-----------|---------|-------|---------------|
| `screening_criteria` | 1.0.0 | `generate_screening_criteria` | `ScreeningCriteriaOutput` |
| `parse_resume` | 1.0.0 | `parse_resume` | `ParsedResume` |

## Контракт

```yaml
id: screening_criteria
version: 1.0.0
skill: generate_screening_criteria
temperature: 0.0          # детерминизм для скрининга
output_format: json
input:
  vacancy_title: string
  seniority: enum
  team: string
  description: string
  requirements: string[]
  nice_to_have: string[]
output_schema: ScreeningCriteriaOutput
model_hint: null           # роутер Cloud.ru выбирает модель
```

Имплементация промптов — в `apps/api/src/ats/modules/ai_core/prompts/` (как код, версионные Pydantic-модели).
Шаблоны — `.txt` файлы рядом с реестром.
