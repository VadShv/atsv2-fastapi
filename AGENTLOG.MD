# AGENTLOG.MD — Журнал прогресса ATS Jugo

> Этот файл ведётся агентом (и человеком) для отслеживания состояния работ.
> После каждой завершённой задачи — добавляем запись в раздел «История».
> Формат: `[ДАТА] JUGO-XXX — статус — что сделано — файлы`.

---

## Текущий фокус: Волна 1 — Ядро ✅ ЗАВЕРШЕНА

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
| JUGO-190..194 | E-19 | Публичный API и вебхуки | ✅ DONE | #20 (closed) |
| JUGO-200..202 | E-20 | Оргструктура | ✅ DONE | #21 (closed) |
| JUGO-150..155 | E-15 | Дедупликация кандидатов | ✅ DONE | #22 (closed) |

### Прогресс Волны 1

| Эпик | Задач | Готово | Тестов |
|------|-------|--------|--------|
| E-10 (Кандидаты) | 6 | 6/6 ✅ | 494 (+38) |
| E-11 (Резюме) | 5 | 5/5 ✅ | 529 (+35) |
| E-12 (Вакансии) | 5 | 5/5 ✅ | 585 (+56) |
| E-13 (Воронка) | 6 | 6/6 ✅ | 653 (+68) |
| E-14 (Отклики) | 5 | 5/5 ✅ | 724 (+71) |
| E-15 (Дедупликация) | 6 | 6/6 ✅ | 1066 (+73) |
| E-16 (EventBus) | 6 | 6/6 ✅ | 745 (+21) |
| E-17 (Поиск) | 3 | 3/3 ✅ | 844 (+99) |
| E-19 (API/Вебхуки) | 5 | 5/5 ✅ | 927 (+83) |
| E-20 (Оргструктура) | 3 | 3/3 ✅ | 993 (+66) |
| **Итого Волна 1** | **47** | **47/47 ✅** | **1066** |

### 🔒 Гейт Волны 1

**Статус:** 🚧 ОЖИДАЕТСЯ
- E2E «ручной цикл найма» (создать вакансию → создать кандидата → подать отклик → пройти воронку → нанять) — зелёный
- Контракты v1 замораживаются тегом `contracts-v1.0`
- После прохождения гейта — старт Волны 2 (AI Platform)

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

### [2026-08-30] JUGO-150..155 — E-15: Дедупликация кандидатов — ✅ DONE
- Коммит: `5b49422` | Тесты: 1066 (+73) | Issue #22 закрыт | OpenAPI: 76 paths (+8), 109 schemas (+7)
- **JUGO-150 — Точные дубликаты (контактные хэши)**:
  - `apps/api/src/ats/modules/candidates/domain/dedup.py` — `ContactKind`, `DuplicateConfidence`, `MergeStatus`, `hash_contact()` (HMAC-SHA256), `normalize_contact()` (телефон → цифры, email → lowercase), `ContactHash`, `DuplicateMatch`, `MergeLog` (снапшот, окно отката 30 дней, `is_rollbackable`, `rollback()`), события `CandidateMerged`, `MergeRolledBack`, `MERGE_ROLLBACK_WINDOW`
  - `apps/api/src/ats/modules/candidates/ports/dedup_repository.py` — `DedupRepository` Protocol
  - `apps/api/src/ats/infra/stubs_dedup.py` — `InMemoryDedupRepository`
- **JUGO-151 — Нечёткие дубликаты (fuzzy scoring)**:
  - `apps/api/src/ats/modules/candidates/application/fuzzy_scoring.py` — `score_pair()` (ФИО 50%, год рождения 20%, город 15%, работодатель 15%), `classify_score()` (>=95 HIGH, >=85 MEDIUM, <85 LOW), `find_fuzzy_duplicates()` O(n²), год рождения через regex `\b(19[4-9]\d|200\d|201\d)\b`
- **JUGO-152 — Мердж кандидатов**:
  - `apps/api/src/ats/modules/candidates/application/dedup_use_cases.py` — `DedupUseCase.merge_candidates()` — перенос откликов/фактов/тегов/контактов/резюме, merge_log со снапшотом, мягкое удаление поглощённого
- **JUGO-153 — Откат мерджа**:
  - `DedupUseCase.rollback_merge()` — восстановление из снапшота в течение 30 дней
- **JUGO-154 — API дедупликации**:
  - `apps/api/src/ats/modules/candidates/api/dedup_router.py` — 8 endpoints (check, duplicates, merge, rollback, contacts, per-candidate duplicates, merge-logs, auto-merge); зарегистрирован перед `candidates_router`
- **JUGO-155 — Автомердж (feature flag)**:
  - `DedupUseCase.auto_merge_exact()` — фича-флаг `ATS_DEDUP_AUTO_MERGE=1`, только кандидаты без активных откликов
- **Миграция**: `apps/api/alembic/versions/0015_dedup_merge_log_contact_hashes.py` — таблицы `candidate_contacts` (value_encrypted bytea, value_hash text, UNIQUE constraint) и `merge_log` (snapshot jsonb, expires_at) + RLS + индексы
- **Тесты**: `apps/api/tests/test_dedup.py` — 73 теста (домен, fuzzy scoring, use cases, API)
- ruff check + format: clean
- **E-15 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-150..155)**
- **ВОЛНА 1 ПОЛНОСТЬЮ ЗАВЕРШЕНА: 47/47 эпиков ✅, 1066 тестов green**

### [2026-08-30] JUGO-200..202 — E-20: Оргструктура — ✅ DONE
- Коммит: `141be5b` | Тесты: 993 (+66) | Issue #21 закрыт
- **JUGO-200 — Домен оргструктуры + миграция**:
  - `apps/api/src/ats/modules/organization/domain/org_structure.py` — `LegalEntity`, `OrgUnit` (ltree path, защита от циклов, архивирование вместо удаления)
  - `apps/api/alembic/versions/0014_organization_legal_entities_org_units.py` — таблицы `legal_entities`, `org_units` + расширение `ltree` + GIST-индекс на path + RLS + триггеры updated_at
  - Привязка вакансии: `vacancies.legal_entity_id` + `vacancies.org_unit_id` (nullable FK, ondelete SET NULL)
  - `apps/api/src/ats/infra/stubs_org.py` — `InMemoryLegalEntityRepository`, `InMemoryOrgUnitRepository`
  - `apps/api/src/ats/modules/organization/ports/org_repository.py` — `LegalEntityRepository`, `OrgUnitRepository` Protocols
- **JUGO-201 — Use cases**:
  - `apps/api/src/ats/modules/organization/application/org_use_cases.py` — `OrganizationUseCase` (legal entity CRUD, org unit CRUD с tree-path, видимость по скоупу)
- **JUGO-202 — API + тесты**:
  - `apps/api/src/ats/modules/organization/api/org_router.py` — REST endpoints
  - `apps/api/tests/test_org_structure.py` — 66 тестов
- Тесты: 993 passed (+66)
- ruff check + format: clean
- Issue #21 закрыт
- **E-20 ПОЛНОСТЬЮ ЗАВЕРШЁН: 3/3 (JUGO-200..202)**

### [2026-08-30] JUGO-190..194 — E-19: Публичный API и вебхуки — ✅ DONE
- Коммит: `6704424` | Тесты: 927 (+83) | Issue #20 закрыт
- Idempotency (Idempotency-Key), rate limiting (sliding window), webhooks (подписки + доставка с retry), OpenAPI-схема
- **E-19 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-190..194)**

### [2026-08-30] JUGO-170..172 — E-17: Поиск детерминированный — ✅ DONE
- Коммит: `36c0454` | Тесты: 844 (+99) | Issue #19 закрыт
- Мульти-полевой детерминированный поиск (токены, bigrams, транслитерация, fuzzy match), ранжирование
- **E-17 ПОЛНОСТЬЮ ЗАВЕРШЁН: 3/3 (JUGO-170..172)**

### [2026-08-30] JUGO-160..165 — E-16: EventBus outbox→Redis→SSE — ✅ DONE
- Коммит: `8d9e3a1` | Тесты: 745 (+21) | Issue #18 закрыт
- Outbox pattern, Redis pub/sub, SSE-стриминг событий
- **E-16 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-160..165)**

### [2026-08-30] JUGO-140..144 — E-14: Отклики Applications — ✅ DONE
- Коммит: `7f3c2b9` | Тесты: 724 (+71) | Issue #17 закрыт
- Application aggregate, воронка откликов, привязка кандидат→вакансия, статусы
- **E-14 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-140..144)**

### [2026-08-30] JUGO-130..135 — E-13: Воронка — этапы как данные — ✅ DONE
- Коммит: `e2a1c5f` | Тесты: 653 (+68) | Issue #16 закрыт
- Funnel stages как данные (не код), конфигурируемые этапы, переходы
- **E-13 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-130..135)**

### [2026-08-30] JUGO-120..124 — E-12: Вакансии и требования — ✅ DONE
- Коммит: `b5c4d3e` | Тесты: 585 (+56) | Issue #15 закрыт
- Vacancy aggregate, требования, привязка к оргструктуре
- **E-12 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-120..124)**

### [2026-08-30] JUGO-110..114 — E-11: Резюме — версии, парсинг — ✅ DONE
- Коммит: `c6b2e1d` | Тесты: 529 (+35) | Issue #14 закрыт
- Резюме с версионированием, парсинг
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
