# ATS Core

AI-native ATS (Applicant Tracking System). Референс по функциональности — Huntflow.

## Принципы

- **AI NATIVE** — AI встроен в поток (создал вакансию → ИИ сгенерил критерии скрининга).
- **WHITEBOX AI** — каждый AI-вывод имеет провенанс: модель, версию промпта, хэш входа, сырой и распарсенный вывод, reasoning. Любое решение объяснимо.
- **SECURE FIRST** — мультитенант через RLS, PII-изоляция, RBAC+ABAC, audit log, секреты из env.
- **УСТОЙЧИВОСТЬ** — outbox, идемпотентность, retry/fallback, graceful degradation.
- **ДОСТУПНОСТЬ** — WCAG 2.2 AA.
- **USERFRIENDLY** — progressive disclosure, inline AI-предложения с accept/reject.
- **СКОРОСТЬ** — streaming AI, индексы, тяжёлый AI в фоне.
- **БЫСТРЕЙШИЙ ПОИСК** — гибридный поиск (BM25 + vector), re-rank, p95 < 100 мс.

## Архитектура

Модульный монолит + Ports & Adapters (гексагонал). Модули общаются через доменные
события. См. `docs/adr/ADR-0001-core-architecture.md`.

```
apps/api/src/ats/
  shared/            # shared kernel: IDs, Result, aggregate, events
  modules/
    identity/        # users, auth, RBAC+ABAC, tenants
    recruitment/     # вакансии, pipeline, transitions
    candidates/      # candidate 360, документы
    ai_core/         # AIGateway, prompts, provenance, skills
    search/          # индексация, гибридный поиск
    audit/           # audit log, consent, PII-vault
  infra/             # adapters: db, ai, search, events, stubs
```

## Стек

- Python 3.11+ / FastAPI / Pydantic v2 / SQLAlchemy 2.0 async
- PostgreSQL 16 + pgvector (RLS)
- Redis (кэш/шина)
- LiteLLM (AI Gateway)
- Next.js 15 (фронт, в планах)

## Быстрый старт (dev, без БД/LLM)

```bash
cd apps/api
export ATS_STUB_MODE=1
PYTHONPATH=src python3 -m ats.main  # или: uvicorn ats.main:app
```

Stub-режим использует in-memory репозитории и stub-AI, возвращает предзаготовленные
критерии. Полноценный запуск (Postgres + реальная LLM) — через Docker Compose.

## API

- `POST /api/v1/vacancies` — создать вакансию + AI-критерии скрининга
- `GET /health` — health check

### Пример

```bash
curl -X POST http://localhost:8000/api/v1/vacancies \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Middle Python Developer",
    "seniority": "middle",
    "team": "Backend",
    "description": "Backend на FastAPI+PostgreSQL. Нужно: Python 3.10+, REST API, async.",
    "requirements": ["Python 3.10+", "FastAPI", "PostgreSQL"]
  }'
```

## Статус

- [x] Shared kernel (IDs, Result, aggregate, events)
- [x] AI Core: AIGateway (LiteLLM) + prompt registry + provenance port + JSON-repair
- [x] Skill: генерация критериев скрининга из описания роли
- [x] Агрегат Vacancy + use case создания вакансии
- [x] HTTP API: POST /vacancies (stub-режим)
- [ ] Postgres-адаптеры + миграции (RLS)
- [ ] Pipeline кандидатов (стадии как Huntflow)
- [ ] Парсинг резюме
- [ ] Гибридный поиск (pgvector)
- [ ] Фронт: визард создания вакансии с AI-критериями
