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
| JUGO-120..124 | E-12 | Вакансии и требования | ⬜ PENDING | #15 |
| JUGO-130..135 | E-13 | Воронка — этапы как данные | ⬜ PENDING | #16 |
| JUGO-140..144 | E-14 | Отклики Applications | ⬜ PENDING | #17 |
| JUGO-160..165 | E-16 | EventBus outbox→Redis→SSE | ⬜ PENDING | #18 |
| JUGO-170..172 | E-17 | Поиск детерминированный | ⬜ PENDING | #19 |
| JUGO-190..194 | E-19 | Публичный API и вебхуки | ⬜ PENDING | #20 |
| JUGO-200..202 | E-20 | Оргструктура | ⬜ PENDING | #21 |
| JUGO-150..155 | E-15 | Дедупликация кандидатов | ⬜ PENDING | #22 |

### Прогресс Волны 1

| Эпик | Задач | Готово | Тестов |
|------|-------|--------|--------|
| E-10 (Кандидаты) | 6 | 6/6 ✅ | 494 (+38) |
| E-11 (Резюме) | 5 | 5/5 ✅ | 529 (+35) |
| **Итого** | **11** | **11/11 ✅** | **529** |

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

### [2026-08-30] JUGO-110..114 — E-11: Резюме — версии, парсинг — ✅ DONE
- Коммит: `268f516` | Тесты: 529 (+35) | Issue #14 закрыт
- Файлы:
  - `apps/api/src/ats/modules/candidates/domain/resume.py` — домен резюме: `ResumeSourceKind` (8 типов), `ResumeVersionStatus` (5 статусов), `ResumeFileType` (4 формата), `DEBOUNCE_WINDOW_SECONDS=600`, `ResumeVersionCreated` event, `ResumeSource` dataclass, `ResumeVersion` (AggregateRoot: create/mark_parsing/mark_parsed/mark_failed/mark_needs_manual_review/is_within_debounce_window), `compute_content_hash()` (SHA-256), `detect_file_type()`
  - `apps/api/src/ats/shared/events.py` — регистр: `ResumeVersionCreated` + поля `version_number`, `content_hash`, `source_kind`, `file_type` + fallback `_extract_aggregate_id` на `version_id`
  - `apps/api/src/ats/infra/db/models/candidates.py` — ORM: `ResumeSourceORM`, `ResumeVersionORM` (content_hash, status, parser_version, provenance_id, parsed_data JSONB, parse_error)
  - `apps/api/alembic/versions/0009_resume_sources_versions.py` — миграция: таблицы `resume_sources` + `resume_versions` с RLS + уникальный индекс `ux_resume_versions_candidate_hash` для дедупликации
  - `apps/api/src/ats/modules/candidates/ports/resume_repository.py` — `ResumeRepository` Protocol (save_source, get_source, save_version, get_version, list_versions, find_by_content_hash, get_next_version_number)
  - `apps/api/src/ats/infra/stubs_resume_repository.py` — `InMemoryResumeRepository` (полная реализация порта)
  - `apps/api/src/ats/infra/ai/text_extraction.py` — JUGO-111: добавлена `_extract_html()` через stdlib `html.parser` (пропускает script/style/head/meta), поддержка `.html/.htm` в `extract_text()`
  - `apps/api/src/ats/modules/candidates/domain/parsed_resume.py` — JUGO-112: добавлена `LanguageSkill` модель + поле `languages: list[LanguageSkill]` в `ParsedResume`
  - `apps/api/src/ats/infra/ai/stub_outputs.py` — stub-вывод `parse_resume` расширен: `languages` (Русский/родной, Английский/B2)
  - `apps/api/src/ats/modules/candidates/application/upload_candidate_resume.py` — JUGO-113+114: `UploadCandidateResumeUseCase` (проверка кандидата → detect_file_type → content-hash дедупликация + debounce → create source + version (PENDING) → extract text → AI parse → mark_parsed → attach_resume → update_profile → auto-facts sync → reindex). `_sync_facts_from_resume()`: EXPERIENCE/SKILL/EDUCATION/LANGUAGE факты, `_should_create_fact()` + `_same_natural_key()` — не перезаписывает pinned/manual факты
  - `apps/api/src/ats/infra/container.py` — `resume_repository` (InMemoryResumeRepository) + `upload_candidate_resume` (UploadCandidateResumeUseCase) в Container
  - `apps/api/src/ats/modules/candidates/api/schemas.py` — 3 новые схемы: `ResumeVersionResponse`, `ResumeVersionListResponse`, `UploadResumeResponse`
  - `apps/api/src/ats/modules/candidates/api/router.py` — 2 новых эндпоинта: `POST /candidates/{id}/resumes` (multipart upload → version + parsing + facts) + `GET /candidates/{id}/resumes` (список версий). Расширены `ALLOWED_EXTENSIONS` (.html, .htm)
  - `apps/api/tests/test_resume_versions.py` — 35 тестов: домен (content_hash, detect_file_type, ResumeSource, ResumeVersion lifecycle, debounce), HTML extraction, use case (создание версии + фактов, дедупликация, pinned-факты, language-факты, несуществующий кандидат, неподдерживаемый формат, provenance, множественные версии), ParsedResume.languages
- Тесты: 529 passed (+35)
- ruff check + format: clean
- Issue #14 закрыт
- **E-11 ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5 (JUGO-110..114)**

### [2026-08-30] JUGO-100..105 — E-10: Кандидаты — мастер-профиль — ✅ DONE
- Коммит: `95d9742` | Тесты: 494 (+38) | Issue #13 закрыт
- Файлы:
  - `apps/api/src/ats/modules/candidates/domain/candidate.py` — расширение: поля `location`, `updated_at`; методы `update_profile()` (patch-семантика + событие CandidateUpdated), `attach_resume()` (событие ResumeAttached), `to_registry_dict()`
  - `apps/api/src/ats/modules/candidates/domain/facts.py` — факты профиля: `FactType` (experience, skill, education, language, certification), `FactSource` (resume_version, manual, import, ai_inference), `CandidateFact` (pinned, confidence, source_ref, can_be_overwritten_by), `build_experience_fact()`, `build_skill_fact()`
  - `apps/api/src/ats/modules/candidates/domain/tags.py` — теги и blacklist: `BlacklistReason` (5 жёстких причин), `CandidateTag`, `BlacklistEntry` (только admin/head_of_recruiting)
  - `apps/api/src/ats/infra/db/models/candidates.py` — ORM: `CandidateFactORM`, `CandidateTagORM`, `CandidateBlacklistORM` + `location` в `CandidateORM`
  - `apps/api/alembic/versions/0008_candidate_facts_tags_blacklist.py` — миграция: 3 новые таблицы + `location` колонка + RLS
  - `apps/api/src/ats/modules/candidates/ports/candidate_repository.py` — порт расширен до 15 методов (CRUD + facts + tags + blacklist)
  - `apps/api/src/ats/infra/stubs_repositories.py` — `InMemoryCandidateRepository` реализует полный порт
  - `apps/api/src/ats/modules/candidates/application/candidate_crud.py` — `CandidateCrudUseCase` + `BulkImportCandidatesUseCase`
  - `apps/api/src/ats/modules/candidates/api/schemas.py` — 14 Pydantic-моделей для REST API
  - `apps/api/src/ats/modules/candidates/api/router.py` — REST API: 14 эндпоинтов (CRUD + facts + tags + blacklist + bulk import + upload resume)
  - `apps/api/src/ats/modules/candidates/application/__init__.py` — экспорт новых use cases
  - `apps/api/src/ats/infra/container.py` — `candidate_crud` + `bulk_import_candidates` в Container
  - `apps/api/src/ats/shared/events.py` — регистр событий: `CandidateUpdated`, `ResumeAttached` + `fields_changed` в payload
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
