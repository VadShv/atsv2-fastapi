# AGENTLOG.MD — Журнал прогресса ATS Jugo

> Этот файл ведётся агентом (и человеком) для отслеживания состояния работ.
> После каждой завершённой задачи — добавляем запись в раздел «История».
> Формат: `[ДАТА] JUGO-XXX — статус — что сделано — файлы`.

---

## Текущий фокус: Волна 1 — Ядро 🚧 В РАБОТЕ

**Цель волны:** ядро ATS — кандидаты, резюме, вакансии, воронка, отклики, поиск, события, API.

### Карта задач Волны 1

| JUGO | Эпик | Описание | Статус | Issue |
|------|------|----------|--------|-------|
| JUGO-100..105 | E-10 | Кандидаты — мастер-профиль | ✅ DONE | #13 (closed) |
| JUGO-110..114 | E-11 | Резюме — версии, парсинг | ✅ DONE | #14 (closed) |
| JUGO-120..124 | E-12 | Вакансии и требования | ✅ DONE | #15 (closed) |
| JUGO-130..135 | E-13 | Воронка — этапы как данные | ✅ DONE | #16 (closed) |
| JUGO-140..144 | E-14 | Отклики Applications | ✅ DONE | #17 (closed) |
| JUGO-160..165 | E-16 | EventBus outbox→Redis→SSE | ✅ DONE | #18 (closed) |
| JUGO-170..172 | E-17 | Поиск детерминированный | ✅ DONE | #19 (closed) |
| JUGO-190..194 | E-19 | Публичный API и вебхуки | ⬜ PENDING | #20 |
| JUGO-200..202 | E-20 | Оргструктура | ⬜ PENDING | #21 |
| JUGO-150..155 | E-15 | Дедупликация кандидатов | ⬜ PENDING | #22 |

### Прогресс Волны 1

| Эпик | Задач | Готово | Тестов |
|------|-------|--------|--------|
| E-10 (Кандидаты) | 6 | 6/6 ✅ | 494 (+38) |
| E-11 (Резюме) | 5 | 5/5 ✅ | 529 (+35) |
| E-12 (Вакансии) | 5 | 5/5 ✅ | 585 (+56) |
| E-13 (Воронка) | 6 | 6/6 ✅ | 653 (+68) |
| E-14 (Отклики) | 5 | 5/5 ✅ | 724 (+71) |
| E-16 (EventBus) | 6 | 6/6 ✅ | 745 (+21) |
| E-17 (Поиск) | 3 | 3/3 ✅ | 844 (+99) |
| **Итого с E-17** | **36** | **36/36 ✅** | **844** |

---

## Волна 0 — Гейт ✅ ЗАВЕРШЕНА

**Цель гейта:** пустое приложение с логином, ролями, аудитом, метриками и зелёным CI.

### Карта задач

| JUGO | Эпик | Описание | Статус | Issue |
|------|------|----------|--------|-------|
| JUGO-010 | E-01 | docker-compose (pg+pgvector, redis, api, web, worker) | ✅ DONE | — |
| JUGO-011 | E-01 | Alembic (миграции 0001–0007) | ✅ DONE | — |
| JUGO-012 | E-01 | Каркас воркеров arq (5 очередей, BaseTask) | ✅ DONE | — |
| JUGO-013 | E-01 | S3-клиент + модуль core/files | ✅ DONE | #6 (closed) |
| JUGO-014 | E-01 | Сиды демо-данных (5к кандидатов, 20 вакансий) | ✅ DONE | #7 (closed) |
| JUGO-020 | E-02 | Модель users/roles/permissions + скоупы | ✅ DONE | — |
| JUGO-021 | E-02 | Сессии — refresh + rate limit + CSRF | ✅ DONE | #8 (closed) |
| JUGO-022 | E-02 | Permission-чекер deny-by-default | ✅ DONE | — |
| JUGO-023 | E-02 | 2FA (TOTP) для админ-ролей | ✅ DONE | #9 (closed) |
| JUGO-025 | E-02 | API-ключи со скоупами | ✅ DONE | #10 (closed) |
| JUGO-026 | E-02 | OIDC/SSO — абстракция identity-провайдера | ✅ DONE | #11 (closed) |
| JUGO-027 | CI | GitHub Actions pipeline (lint + mypy + tests) | ✅ DONE | #12 (closed) |

**ВОЛНА 0 ПОЛНОСТЬЮ ЗАВЕРШЕНА — 12/12 ✅, 456 тестов, CI green**

---

## История изменений

### [2026-08-30] JUGO-170..172 — E-17: Поиск детерминированный — ✅ DONE
- Коммит: `206de35` | Тесты: 844 (+99) | Issue #19 закрыт
- **JUGO-170 — Поисковый вектор (aggregate)**:
  - `apps/api/src/ats/modules/search/domain/models.py` — `build_search_text()`: агрегация ФИО+заголовок+навыки+компании+резюме с дедупликацией полных строк
  - `apps/api/alembic/versions/0013_search_vector_russian_simple.py` — tsvector конфиг `russian,simple` + таблица `search_synonyms` с RLS
  - `apps/api/src/ats/infra/search/pgvector_search_engine.py` — `to_tsvector('russian,simple', ...)` в `index()`
- **JUGO-171 — Булев парсер запросов**:
  - `apps/api/src/ats/modules/search/domain/query_parser.py` — `tokenize()`, `_Parser` (рекурсивный спуск: OR→AND→NOT→primary), AST-ноды (`TermNode`, `PhraseNode`, `AndNode`, `OrNode`, `NotNode`), `parse_query()`, `has_boolean_syntax()`, `to_tsquery_string()`, `evaluate()`, `extract_terms()`, `expand_synonyms()`, `QueryParseError` (с `message`+`hint`+`position`, подсказки на русском)
  - Интеграция: булевы запросы → `to_tsquery` (жёсткая фильтрация `@@`), plain → `plainto_tsquery` (мягкий поиск без фильтрации, OR-семантика для максимального recall)
  - `apps/api/src/ats/infra/search/in_memory_search_engine.py` — `_parse_query()` возвращает `(ast, is_boolean)`; жёсткая булева фильтрация только при `is_boolean=True`
  - `apps/api/src/ats/modules/search/application/search_candidates.py` — валидация запроса через `parse_query()`, возвращает 400 с подсказкой при `QueryParseError`
- **JUGO-172 — Словарь синонимов**:
  - `apps/api/src/ats/modules/search/domain/synonym.py` — `SynonymEntry` с нормализацией term, дедупликацией synonyms
  - `apps/api/src/ats/modules/search/ports/synonym_repository.py` — `SynonymRepository` Protocol
  - `apps/api/src/ats/infra/stubs_search.py` — `InMemorySynonymRepository` с tenant isolation
  - `apps/api/src/ats/modules/search/domain/models.py` — `SearchQuery.synonym_map` поле
  - `apps/api/src/ats/infra/container.py` — `synonym_repository` добавлен в `Container` и `build_container()`
  - `apps/api/src/ats/modules/search/api/router.py` — CRUD endpoints `GET/POST/DELETE /search/synonyms`, `GET /search/synonyms/{id}`
  - Расширение: синонимы расширяют только `TermNode` (не `PhraseNode`)
- Тесты: `apps/api/tests/test_search_boolean.py` — 99 тестов (tokenizer, parser, tsquery, evaluate, extract_terms, expand_synonyms, in-memory boolean search, synonyms domain+repo+API, syntax errors via API)
- Тесты: 844 passed (+99)
- ruff check src/: clean, ruff format src/: clean
- Issue #19 закрыт
- **E-17 ПОЛНОСТЬЮ ЗАВЕРШЁН: 3/3 (JUGO-170..172)**

### [2026-08-30] JUGO-160..165 — E-16: EventBus outbox→Redis→SSE — ✅ DONE
- Коммит: `c191cdf` | Тесты: 745 (+21) | Issue #18 закрыт
- Файлы:
  - `contracts/events/` — 3 новые JSON-схемы (funnel.preset.published, application.funnel.transition, application.hm.decision); `registry.v1.json` обновлён: 20 событий (18 доменных + 2 AI stubs для Волны 2)
  - `infra/events/bus.py` — InProcessEventBus: `subscribe_queue()`/`unsubscribe_queue()`/`publish_envelope()` для доставки конвертов в SSE черів queue subscription
  - `infra/events/outbox.py` — OutboxRelay воркер: читает outbox, публикует в InProcessEventBus, помечает processed
  - `infra/events/sse.py` — SSE endpoint с queue subscription + replay
  - `infra/events/metrics.py` — Prometheus метрики событий
  - `apps/api/tests/contracts/test_event_contracts.py` — валидация JSON-схем
  - `apps/api/tests/test_workers.py` — тесты outbox relay
- Тесты: 745 passed (+21)
- ruff check + format: clean
- Issue #18 закрыт
- **E-16 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-160..165)**

### [2026-08-30] JUGO-140..144 — E-14: Отклики Applications — ✅ DONE
- Коммит: `1a9f2b3` | Тесты: 724 (+71) | Issue #17 закрыт
- Файлы:
  - `apps/api/src/ats/modules/recruitment/domain/applications.py` — `Application`, `ApplicationStatus`, `ApplicationEvent`, event sourcing
  - `apps/api/src/ats/modules/recruitment/api/applications_router.py` — REST endpoints
  - `apps/api/tests/test_applications_domain.py` — доменные тесты
  - `apps/api/tests/test_applications_api.py` — API тесты
  - `apps/api/tests/test_applications_use_cases.py` — use case тесты
- Тесты: 724 passed (+71)
- ruff check + format: clean
- Issue #17 закрыт
- **E-14 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-140..144)**

### [2026-08-30] JUGO-130..135 — E-13: Воронка — этапы как данные — ✅ DONE
- Коммит: `2f0c1e9` | Тесты: 653 (+68) | Issue #16 закрыт
- Файлы:
  - `apps/api/src/ats/modules/recruitment/domain/funnel.py` — `Funnel`, `FunnelStage`, `StageType`
  - `apps/api/src/ats/modules/recruitment/api/funnel_router.py` — REST endpoints
  - `apps/api/tests/test_recruitment.py` — тесты воронки
- Тесты: 653 passed (+68)
- ruff check + format: clean
- Issue #16 закрыт
- **E-13 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-130..135)**

### [2026-08-30] JUGO-120..124 — E-12: Вакансии и требования — ✅ DONE
- Коммит: `e3a4c2b` | Тесты: 585 (+56) | Issue #15 закрыт
- Файлы:
  - `apps/api/src/ats/modules/recruitment/domain/vacancy.py` — `Vacancy`, `VacancyRequirement`
  - `apps/api/src/ats/modules/recruitment/api/vacancy_router.py` — REST endpoints
  - `apps/api/tests/test_vacancy_requirements.py` — тесты вакансий и требований
- Тесты: 585 passed (+56)
- ruff check + format: clean
- Issue #15 закрыт
- **E-12 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-120..124)**

### [2026-08-30] JUGO-110..114 — E-11: Резюме — версии, парсинг — ✅ DONE
- Коммит: `f8d9a1c` | Тесты: 529 (+35) | Issue #14 закрыт
- Файлы:
  - `apps/api/src/ats/modules/candidates/domain/resume.py` — `Resume`, `ResumeVersion`
  - `apps/api/src/ats/modules/candidates/application/upload_resume.py` — парсинг резюме
  - `apps/api/tests/test_resume_versions.py` — тесты версий резюме
  - `apps/api/tests/test_resume_parsing.py` — тесты парсинга
- Тесты: 529 passed (+35)
- ruff check + format: clean
- Issue #14 закрыт
- **E-11 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-110..114)**

### [2026-08-30] JUGO-100..105 — E-10: Кандидаты — мастер-профиль — ✅ DONE
- Коммит: `4a5b2c8` | Тесты: 494 (+38) | Issue #13 закрыт
- Файлы:
  - `apps/api/src/ats/modules/candidates/domain/candidate.py` — `Candidate`, `CandidateFact`, `CandidateTag`
  - `apps/api/src/ats/modules/candidates/api/candidates_router.py` — REST endpoints
  - `apps/api/tests/test_candidates.py` — 38 тестов (домен, CRUD, факты, теги, blacklist, массовый импорт)
- Тесты: 494 passed (+38)
- ruff check + format: clean
- Issue #13 закрыт
- **E-10 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-100..105)**

### [2026-08-30] JUGO-027 — CI fixes (3 commits: a8ad041, 073c3a9, 6d4e6ef)
- 3 fix-коммита чтобы CI pipeline стал зелёным:
  1. `a8ad041` — structlog `PrintLoggerFactory` → `stdlib.LoggerFactory`
  2. `073c3a9` — `request.url.host` → `request.url.hostname` (starlette совместимость)
  3. `6d4e6ef` — tracing propagation fallback + `test_storage` mock `aioboto3` через `sys.modules`
- CI статус: **Tests ✅ + Lint ✅ green, mypy advisory (non-blocking)**
- **ВОЛНА 0 ПОЛНОСТЬЮ ЗАВЕРШЕНА: 12/12 задач, 456 тестов green, CI green ✅**

### [2026-08-30] JUGO-027 — CI: GitHub Actions pipeline — ✅ DONE
- Коммит: `40c7d31` | Тесты: 456 | Issue #12 закрыт
- Файлы:
  - `.github/workflows/ci.yml` — 3 job: lint (ruff, blocking), mypy (advisory), tests (456 green)
  - `apps/api/pyproject.toml` — ruff ignore rules + auto-fixes + format
  - `README.md` — CI badge added
- Тесты: 456 passed
- Issue #12 закрыт

### [2026-08-29] JUGO-026 — OIDC/SSO — ✅ DONE
- Коммит: `a47c99b` | Тесты: 456 (+24) | Issue #11 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/oidc.py` — OIDC модели, PKCE helpers
  - `apps/api/src/ats/modules/identity/ports/identity_provider.py` — `IdentityProvider` Protocol
  - `apps/api/src/ats/modules/identity/infra/stub_identity_provider.py` — `StubIdentityProvider`
  - `apps/api/src/ats/modules/identity/infra/oidc_settings.py` — `OIDCSettings`
  - `apps/api/src/ats/modules/identity/api/router.py` — OIDC endpoints
  - `apps/api/tests/test_oidc.py` — 24 теста
- Тесты: 456 passed (+24)
- Issue #11 закрыт

### [2026-08-29] JUGO-025 — API-ключи — ✅ DONE
- Коммит: `1577581` | Тесты: 432 (+23) | Issue #10 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/api_key.py` — `APIKey`, `APIKeyScope`
  - `apps/api/src/ats/modules/identity/ports/api_key.py` — `APIKeyStore` Protocol
  - `apps/api/src/ats/modules/identity/infra/in_memory_api_key.py` — `InMemoryAPIKeyStore`
  - `apps/api/src/ats/modules/identity/api/router.py` — API key CRUD endpoints
  - `apps/api/tests/test_api_keys.py` — 23 теста
- Тесты: 432 passed (+23)
- Issue #10 закрыт

### [2026-08-29] JUGO-023 — 2FA (TOTP) — ✅ DONE
- Коммит: `3ca59dc` | Тесты: 409 (+37) | Issue #9 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/totp.py` — TOTP на чистом stdlib
  - `apps/api/src/ats/modules/identity/domain/two_factor.py` — `TwoFactorConfig`, `ROLES_REQUIRING_2FA`
  - `apps/api/src/ats/modules/identity/ports/two_factor.py` — `TwoFactorStore` Protocol
  - `apps/api/src/ats/modules/identity/infra/in_memory_2fa.py` — `InMemoryTwoFactorStore`
  - `apps/api/src/ats/modules/identity/infra/runtime.py` — singleton + reset
  - `apps/api/src/ats/modules/identity/api/router.py` — 2FA endpoints
  - `apps/api/tests/test_2fa.py` — 37 тестов
- Тесты: 409 passed (+37)
- Issue #9 закрыт

### [2026-08-29] JUGO-021 — Сессии — ✅ DONE
- Коммит: `38d38b2` | Тесты: 390 (+19) | Issue #8 закрыт
- Тесты: 390 passed (+19)
- Issue #8 закрыт

### [2026-08-29] Волна 0 — Наблюдаемость + Файлы + Сиды
- JUGO-032 (Логи + PII): +27 тестов, `69c1dc4`
- JUGO-030 (OTel): +29 тестов, `fbfb504`
- JUGO-031 (Prometheus): +28 тестов, `9e2dd0d`
- JUGO-033 (Audit partition): +24 теста, `eba7513`
- JUGO-034 (Sentry + alerts): +23 теста, `f8a1915`
- JUGO-013 (S3 + core/files): +45 тестов, `1a8d38c`
- JUGO-014 (Сиды демо-данных): +38 тестов, `82aa700`

### [2026-08-29] Волна 0 — старт
- Создан milestone «Волна 0 — Гейт» (#1) на GitHub
- Созданы 12 issues (#1–#12) для всех задач Волны 0
- Создан AGENTLOG.MD
- Зафиксировано текущее состояние: 144 теста green, деплой на сервере работает

---
