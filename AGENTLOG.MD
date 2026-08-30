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
| JUGO-170..172 | E-17 | Поиск детерминированный | ⬜ PENDING | #19 |
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
| **Итого** | **27** | **27/27 ✅** | **724** |
| **Итого с E-16** | **33** | **33/33 ✅** | **745** |

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

### [2026-08-30] JUGO-160..165 — E-16: EventBus outbox→Redis→SSE — ✅ DONE
- Коммит: `c191cdf` | Тесты: 745 (+21) | Issue #18 закрыт
- Файлы:
  - `contracts/events/` — 3 новые JSON-схемы (funnel.preset.published, application.funnel.transition, application.hm.decision); `registry.v1.json` обновлён: 20 событий (18 доменных + 2 AI stubs для Волны 2)
  - `infra/events/bus.py` — InProcessEventBus: `subscribe_queue()`/`unsubscribe_queue()`/`publish_envelope()` для доставки конвертов в SSE через `asyncio.Queue` (non-blocking, drop при переполнении)
  - `modules/events/api/router.py` — полная реализация SSE: heartbeat, фильтрация по `types`, reconnect по `Last-Event-ID`, in-process очередь (stub mode)
  - `infra/events/consumer.py` — `replay(start_id, count, event_types)`: повторная обработка из Redis Stream (xrange) с фильтром
  - `infra/events/relay.py` — метрики Prometheus: `outbox_failed_total`, `outbox_lag_seconds` (ленивый импорт, no-op fallback)
  - `infra/metrics/registry.py` — добавлены `outbox_failed_total` (Counter) и `outbox_lag_seconds` (Gauge)
  - `shared/events.py` — `_resolve_payload` конвертирует tuple/set → list (jsonschema compat); добавлен `version_id` в `_PAYLOAD_FIELDS`
  - `modules/candidates/domain/resume.py` — `ResumeVersionCreated` получил поле `version_id` (aggregate resolution для resume)
  - `tests/contracts/test_event_contracts.py` — 20 контрактных тестов для всех событий + проверка registry
  - `tests/test_event_bus.py` — тесты SSE-очередей, replay, format_sse (+21 тест)
- Тесты: 745 passed (+21)
- Issue #18 закрыт

### [2026-08-30] JUGO-140..144 — E-14: Отклики Applications — ✅ DONE
- Коммит: `3123c38` | Тесты: 724 (+71) | Issue #17 закрыт
- Файлы:
  - `modules/recruitment/domain/application.py` — расширение домена: ApplicationOrigin (INCOMING/COLD_SOURCING/IMPORT/AI_SUGGESTION), RiskLevel, поля origin/current_stage_id/stage_entered_at/screening_score/risk_level/rejection_reason_code/rejection_reason_label/internal_rejection_note/resume_id; методы reject() (с официальной причиной + internal_note), set_risk_level(); свойства is_rejected/is_active; StageTransitionRecord (переименован из StageTransition); событие ApplicationRejected
  - `modules/recruitment/domain/comment.py` — новый домен: CommentThread (create/add_comment/add_observer/remove_observer/get_public_comments/get_all_comments), Comment (create/edit/add_attachment, @mentions auto-extract), событие CommentPosted
  - `modules/recruitment/ports/application_repository.py` — добавлен list_by_candidate (для JUGO-142)
  - `modules/recruitment/ports/comment_repository.py` — новый порт: save_thread/get_thread/list_by_application
  - `modules/recruitment/application/create_application.py` — обновлён: origin+resume_id параметры, правила повторных откликов (JUGO-142: active → CONFLICT, terminal → новый)
  - `modules/recruitment/application/reject_application.py` — новый use case: отклонение с reason_code + reason_label + internal_note
  - `modules/recruitment/application/comment_use_case.py` — новый use case: create_thread/add_comment/list_threads/add_observer
  - `modules/recruitment/application/application_timeline.py` — новый use case (JUGO-144): агрегация ленты (created/transition/rejection/ai_event/comment) с хронологической сортировкой
  - `modules/recruitment/api/applications_router.py` — расширение REST API: POST /applications (origin+resume), GET /applications (filter by vacancy), GET /{id}, POST /{id}/reject, GET /{id}/timeline, POST /{id}/threads, GET /{id}/threads, POST /{id}/threads/{tid}/comments
  - `infra/stubs_repositories.py` — InMemoryApplicationRepository.list_by_candidate + InMemoryCommentRepository
  - `infra/db/models/applications.py` — ORM расширение (origin, current_stage_id, stage_entered_at, screening_score, risk_level, rejection fields, resume_id)
  - `infra/db/models/comment_threads.py` — новый ORM (comment_threads table)
  - `infra/db/models/__init__.py` — CommentThreadORM registered
  - `alembic/versions/0012_application_enhancements_comments.py` — миграция: расширение applications + таблица comment_threads + RLS
  - `infra/container.py` — reject_application, comment_use_case, application_timeline подключены (stub + prod)
  - `shared/events.py` — ApplicationRejected + CommentPosted зарегистрированы в envelope registry; payload fields: origin, reason_code, reason_label, thread_id, comment_id, author_id, is_private; исправлены отступы в _EVENT_TYPE_REGISTRY
  - `tests/test_applications_domain.py` — 17 тестов (create, reject, risk, screening_score, move_to, states)
  - `tests/test_applications_use_cases.py` — 10 тестов (create с origin+resume, repeat rules, reject, timeline)
  - `tests/test_applications_api.py` — 22 теста (list, get, reject, repeat rules, timeline, comments + mentions + private + attachments)
  - `tests/test_comments_domain.py` — 22 теста (thread, mentions, privacy, attachments, edit, observers)
  - `tests/test_api.py` — обновлён: test_create_application_idempotent → 409 CONFLICT (JUGO-142)
  - `tests/test_pipeline.py` — обновлён: test_create_application_idempotent → conflict (JUGO-142)
- Тесты: 724 passed (+71)
- ruff check + format: clean
- Issue #17 закрыт
- **E-14 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-140..144)**

### [2026-08-30] JUGO-130..135 — E-13: Воронка — этапы как данные — ✅ DONE
- Коммит: `e28b3b9` | Тесты: 653 (+68) | Issue #16 закрыт
- Файлы:
  - `modules/funnel/domain/funnel.py` — полный домен: CanonicalPhase, StageCategory, FunnelStage, FunnelPreset (create/add_stage/publish/archive), FunnelSnapshot (from_preset/is_valid_transition/get_next_stage), StageTransition (с application_id), HMDecision, StageAutomationRule, create_default_preset; события FunnelPresetCreated/Published, FunnelTransitionEvent, HMDecisionRecorded
  - `modules/funnel/application/funnel_use_cases.py` — FunnelPresetUseCase (CRUD + snapshot), FunnelTransitionUseCase (transition с no-op + validity check), HMDecisionUseCase
  - `modules/funnel/ports/` — FunnelPresetRepository, FunnelSnapshotRepository, StageTransitionRepository, HMDecisionRepository
  - `modules/funnel/api/router.py` — REST API: /presets, /stages, /publish, /archive, /snapshot, /transitions, /hm-decisions
  - `infra/stubs_funnel_repositories.py` — InMemory-репозитории (фикс list_by_application фильтра по application_id)
  - `infra/db/models/funnel.py` — ORM: funnel_presets, funnel_snapshots, stage_transitions, hm_decisions, stage_automation_rules
  - `alembic/versions/0011_funnel_presets_snapshots_transitions.py` — миграция + RLS + индексы
  - `infra/container.py` — funnel use cases подключены (stub + prod)
  - `shared/events.py` — регистрация funnel-событий
  - `main.py` — funnel_router зарегистрирован
  - `tests/test_funnel.py` — 68 тестов (домен, use cases, REST API)
- Тесты: 653 passed (+68)
- ruff check + format: clean
- Issue #16 закрыт
- **E-13 ПОЛНОСТЬЮ ЗАВЕРШЁН: 6/6 (JUGO-130..135)**

### [2026-08-30] JUGO-120..124 — E-12: Вакансии и требования — ✅ DONE
- Коммит: `8580e27` | Тесты: 585 (+56) | Issue #15 закрыт
- Файлы:
  - `domain/vacancy.py` — переписан: статусы draft/open/on_hold/closed/canceled, VACANCY_TRANSITIONS, hiring_team, hired_count, closed_at, методы publish/put_on_hold/resume_publishing/close/cancel/increment_hired/update_role, события VacancyPublished/VacancyClosed/VacancyStatusChanged
  - `domain/requirement_set.py` — новый: RequirementOrigin (ai/manual/ai_edited), RequirementSetStatus (draft/active/archived), RequirementSet aggregate (create/activate/archive), событие RequirementSetActivated
  - `ports/requirement_set_repository.py` — новый порт (save/get/list_by_vacancy/get_active/get_next_version)
  - `application/requirement_set_use_case.py` — create/activate/archive/get/list
  - `application/create_vacancy.py` — обновлён: публикует VacancyCreated + VacancyPublished
  - `api/router.py` — обновлён: эндпоинты requirement-sets
  - `infra/stubs.py` — InMemoryRequirementSetRepository
  - `infra/container.py` — requirement_set_use_case подключён
  - `tests/test_recruitment.py` — +56 тестов
- Тесты: 585 passed (+56)
- ruff check + format: clean
- Issue #15 закрыт
- **E-12 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-120..124)**

### [2026-08-30] JUGO-110..114 — E-11: Резюме — версии, парсинг — ✅ DONE
- Коммит: `dc25b9a` | Тесты: 529 (+35) | Issue #14 закрыт
- Тесты: 529 passed (+35)
- Issue #14 закрыт
- **E-11 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-110..114)**

### [2026-08-30] JUGO-100..105 — E-10: Кандидаты — мастер-профиль — ✅ DONE
- Коммит: `f3de41d` | Тесты: 494 (+38) | Issue #13 закрыт
- Файлы:
  - `modules/candidates/domain/candidate.py` — Candidate aggregate: full_name, source, headline, skills, facts, tags, blacklist, контакты
  - `modules/candidates/domain/events.py` — CandidateCreated, CandidateUpdated, FactAdded, TagAdded, Blacklisted
  - `modules/candidates/ports/candidate_repository.py` — CandidateRepository Protocol
  - `modules/candidates/application/candidate_crud.py` — CRUD use cases
  - `modules/candidates/application/bulk_import.py` — BulkImportCandidatesUseCase
  - `modules/candidates/api/router.py` — REST endpoints
  - `infra/stubs.py` — InMemoryCandidateRepository
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
