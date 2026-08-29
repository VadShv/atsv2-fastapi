# AGENTS.md — ATS Core

> Корневые конвенции для всех, кто работает с кодом этого репозитория (людей и агентов).
> Принципы и решения ниже обязательны для всего дерева. Подкаталоги могут иметь свой
> `AGENTS.md`, уточняющий локальные правила; при конфликте побеждает более вложенный файл.

## Проект

**ATS Core** — AI-native система автоматизации подбора персонала.
Функциональный референс: **Huntflow** (пайплайн кандидатов, парсинг резюме, вакансии,
CRM кандидатов, расписание интервью, офферы, воронка и аналитика, интеграции).
Архитектурный референс: принципы ниже.

## Принципы и их воплощение

Каждое архитектурное решение должно быть обосновано одним из принципов.

- **AI NATIVE** — AI встроен в поток, а не прикручен сбоку. Все вызовы LLM идут через
  единый `AIGateway`. AI-навыки (skills) — композируемые use cases, запускаемые по
  доменным событиям (создал вакансию → сгенерил критерии скрининга → распарсил резюме →
  скорил → сматчил). Промпты — это код: версионные, в репозитории, под ревью.
- **WHITEBOX AI** — каждый AI-артефакт имеет провенанс: модель, версию промпта, хэш
  входов, сырой и распарсенный вывод, confidence, латентность, стоимость, timestamp,
  флаг `human_verified`, reasoning trace. Любое AI-решение можно объяснить через
  `explain(artifact_id)`. Детерминизм где возможно (seed, temperature 0).
- **SECURE FIRST** — мультитенант через Row-Level Security (RLS) в Postgres. PII
  изолирован: полевая токенизация/шифрование, consent и retention. RBAC + ABAC.
  Append-only audit log. Валидация схем на каждой границе. Data minimization +
  right-to-erasure. Секреты только из env/vault, никогда в коде.
- **УСТОЙЧИВОСТЬ** — Outbox-паттерн (транзакция БД + события), идемпотентные ключи,
  circuit breaker + retry/backoff, graceful degradation (AI недоступен →
  детерминированный fallback с пометкой `non_ai`), DLQ, tenant-бюджеты токенов.
- **ДОСТУПНОСТЬ (a11y)** — WCAG 2.2 AA: семантический HTML, корректный ARIA,
  keyboard-first, управление фокусом, токены контраста, i18n. AI-выводы в текстовом
  объяснимом виде (не только цвет/балл).
- **USERFRIENDLY** — progressive disclosure, sane defaults, inline AI-предложения с
  accept/reject, bulk-операции, быстрые действия.
- **СКОРОСТЬ** — streaming AI + optimistic UI, индексы, connection pooling, тяжёлый AI
  в фоне, CDN/code-splitting.
- **БЫСТРЕЙШИЙ ПОИСК** — гибридный поиск (BM25 + vector + фильтры), re-ranking,
  фасетная фильтрация, инкрементальная индексация из outbox, p95 < 100 мс, autocomplete.

## Архитектурный стиль

- **Модульный монолит** + **Ports & Adapters (гексагонал)** по каждому модулю.
- Модули общаются **только через доменные события** по in-process шине.
  Запрещено лазить во внутренности другого модуля. Допускается только публичный
  интерфейс модуля.
- Слои внутри модуля (зависимости внутрь):
  1. `domain/` — сущности, value objects, инварианты, доменные события. Чистый, без
     инфраструктурных зависимостей.
  2. `application/` — use cases (commands/queries), оркестрация.
  3. `ports/` — интерфейсы (репозитории, AIGateway, SearchEngine, EventBus, PIIVault).
  4. `infrastructure/` — имплементации (Postgres, AI-провайдеры, поисковый движок).
  5. `api/` — HTTP/transport.

## Стек

- **Backend**: Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + Alembic.
- **БД**: PostgreSQL 16 + pgvector. RLS для мультитенантности.
- **Cache/Bus**: Redis.
- **AI Gateway**: собственный тонкий слой над LiteLLM (роутинг, retry, кэш, метрики).
- **Frontend**: Next.js 15 + React + Tailwind + shadcn/ui + TanStack Query.
- **Runtime**: self-host, Docker Compose (dev) → K8s (prod), multi-tenant через RLS.

## Структура монорепо

```
apps/api/src/ats/
  shared/            # shared kernel: IDs, Result, ошибки, base-классы
  modules/
    identity/        # users, auth, RBAC+ABAC, tenants
    recruitment/     # вакансии, заявки, pipeline stages, transitions
    candidates/      # candidate 360, документы, активити
    ai_core/         # AIGateway, prompts registry, provenance, AI skills
    search/          # индексация, гибридный поиск, ранжирование
    audit/           # audit log, consent, retention, PII-vault
  infra/             # adapters: db, ai, search, events, middleware
apps/web/            # Next.js фронт
docs/                # архитектурные документы и ADR
infra/docker/        # docker-compose, Dockerfiles
```

## Конвенции кода

- Python: `ruff` (lint + format), `mypy --strict` для доменного слоя. `line-length = 100`.
- Импорты: absolute, `from ats.module.layer import ...`.
- Имена: `snake_case` для функций/переменных, `PascalCase` для классов, `UPPER_SNAKE`
  для констант. Доменные события — `PastTenseVerb` (напр. `VacancyCreated`).
- Все публичные функции/методы имеют type hints. Без `Any` в доменном слое.
- Ошибки через `Result`/доменные исключения, не через bare `raise Exception`.
- Идемпотентность: все команды приёмника принимают `IdempotencyKey`.
- Тесты: `pytest`, рядом с модулем в `tests/`. Имя: `test_<что>_<условие>`.
- Коммиты: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- Никаких копирайт-заголовков, если не запрошено явно.
- Не добавлять inline-комментарии, если не запрошено явно.
- Не делать `git commit`/ветки, если не запрошено явно.

## Безопасность (обязательно)

- Секреты — только из env (`.env` в `.gitignore`). Никогда не хардкодить ключи.
- Внешние вызовы — через gateway с таймаутом и circuit breaker.
- Любой пользовательский ввод валидируется Pydantic-схемой.
- SQL — только через параметризованные запросы SQLAlchemy. Никаких f-string в SQL.
- PII (ФИО, контакты) — в PII-vault, в БД только токены/хэши.

## AI-конвенции (whitebox)

- Промпты хранятся как код в `modules/ai_core/prompts/` с версионной схемой.
- Структурированный вывод: JSON-schema + слой «ремонта» (repair) для устойчивости.
- Каждый вызов LLM пишет запись в `provenance_ledger`.
- AI-артефакт (оценка, саммари, критерии) ссылается на `provenance_id`.
- Температура 0 для скрининга/скоринга (детерминизм), выше — для черновиков.
