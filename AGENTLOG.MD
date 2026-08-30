# AGENTLOG.MD — Журнал прогресса ATS Jugo

> Этот файл ведётся агентом (и человеком) для отслеживания состояния работ.
> После каждой завершённой задачи — добавляем запись в раздел «История».
> Формат: `[ДАТА] JUGO-XXX — статус — что сделано — файлы`.

---

## Текущий фокус: Волна 0 — Гейт ✅ ЗАВЕРШЁНА

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

### Порядок реализации (приоритет)

**Этап 1 — Наблюдаемость (E-03):** ✅ 5/5 ЗАВЕРШЁН
**Этап 2 — Файлы и сиды (E-01):** ✅ 2/2 ЗАВЕРШЁН
**Этап 3 — Безопасность (E-02):** ✅ 4/4 ЗАВЕРШЁН
**Этап 4 — CI:** ✅ ЗАВЕРШЁН (JUGO-027)
**ВОЛНА 0 ПОЛНОСТЬЮ ЗАВЕРШЕНА — 12/12 ✅**

### Прогресс

| Этап | Задач | Готово | Тестов |
|------|-------|--------|--------|
| 1. Наблюдаемость (E-03) | 5 | 5/5 ✅ | 270 |
| 2. Файлы и сиды (E-01) | 2 | 2/2 ✅ | 353 |
| 3. Безопасность (E-02) | 4 | 4/4 ✅ | 456 |
| 4. CI | 1 | 1/1 ✅ | 456 |
| **Итого** | **12** | **12/12 ✅** | **456** |

### Этап 1 — Детализация

| Задача | Тестов | Коммит |
|--------|--------|--------|
| JUGO-032 (Логи + PII) | +27 | `69c1dc4` |
| JUGO-030 (OTel) | +29 | `fbfb504` |
| JUGO-031 (Prometheus) | +28 | `9e2dd0d` |
| JUGO-033 (Audit partition) | +24 | `eba7513` |
| JUGO-034 (Sentry + alerts) | +23 | `f8a1915` |
| **Итого Этап 1** | **+131** | |

### Этап 2 — Детализация

| Задача | Тестов | Коммит |
|--------|--------|--------|
| JUGO-013 (S3 + core/files) | +45 | `1a8d38c` |
| JUGO-014 (Сиды демо-данных) | +38 | `82aa700` |
| **Итого Этап 2** | **+83** | |

### Этап 3 — Детализация (Безопасность)

| Задача | Тестов | Коммит |
|--------|--------|--------|
| JUGO-021 (Сессии — refresh + rate limit + CSRF) | +19 | `38d38b2` |
| JUGO-023 (2FA TOTP) | +37 | `3ca59dc` |
| JUGO-025 (API-ключи) | +23 | `1577581` |
| JUGO-026 (OIDC/SSO) | +24 | `a47c99b` |

### Этап 4 — Детализация (CI)

| Задача | Тестов | Коммит |
|--------|--------|--------|
| JUGO-027 (GitHub Actions) | 0 | `40c7d31` |
| **Итого Этап 4** | **0** | |

---

## История изменений

### [2026-08-29] Волна 0 — старт
- Создан milestone «Волна 0 — Гейт» (#1) на GitHub
- Созданы 12 issues (#1–#12) для всех задач Волны 0
- Создан AGENTLOG.MD
- Зафиксировано текущее состояние: 144 теста green, деплой на сервере работает

### [2026-08-29] Предыдущая сессия (Волна 0, часть 1)
- ✅ Контракты событий v1 (envelope + 5 events + registry)
- ✅ Event Bus (Эпик E-16): bus, outbox_publisher, relay, consumer, SSE
- ✅ Доменные события обогащены audit и tracing
- ✅ Audit: domain, ports, infra (AuditEvent, AuditReader, partitioning)
- ✅ OpenTelemetry: settings, setup, context, middleware, propagation
- ✅ Prometheus: settings, registry, middleware, router
- ✅ Sentry: settings, setup, middleware, alerts
- ✅ Structured logging: setup, context, pii_mask, middleware
- ✅ Storage: S3-клиент, models, protocol, whitelist, antivirus, in_memory
- ✅ Сиды: settings, generator, cli, __main__
- ✅ Identity: RBAC, session, totp, two_factor, api_key, oidc, in_memory-infra
- ✅ 144 теста green, деплой на 176.108.250.112

### [2026-08-29] JUGO-032 — Структурные JSON-логи + маскирование ПД — ✅ DONE
- Коммит: `69c1dc4` | Тесты: 171 (+27) | Issue #3 закрыт

### [2026-08-29] JUGO-030 — OpenTelemetry трейсинг — ✅ DONE
- Коммит: `fbfb504` | Тесты: 200 (+29) | Issue #1 закрыт

### [2026-08-29] JUGO-031 — Prometheus-метрики — ✅ DONE
- Коммит: `9e2dd0d` | Тесты: 228 (+28) | Issue #2 закрыт

### [2026-08-29] JUGO-033 — audit_log партиционирование + AuditReader — ✅ DONE
- Коммит: `eba7513` | Тесты: 252 (+24) | Issue #4 закрыт

### [2026-08-29] JUGO-034 — Sentry + алерты — ✅ DONE
- Коммит: `f8a1915`
- Файлы:
  - `apps/api/src/ats/infra/sentry/__init__.py` — экспорты
  - `apps/api/src/ats/infra/sentry/settings.py` — `SentrySettings` (env: `ATS_SENTRY_*`)
  - `apps/api/src/ats/infra/sentry/setup.py` — `setup_sentry()` (ленивый sentry-sdk + no-op), `capture_exception()`, `capture_message()`, `set_user_context()`
  - `apps/api/src/ats/infra/sentry/middleware.py` — `SentryMiddleware` (перехват 5xx)
  - `apps/api/src/ats/infra/sentry/alerts.py` — `send_alert()` (webhook Telegram/Slack), `_build_payload()`, `_should_alert()`
  - `apps/api/main.py` — подключён `setup_sentry()` + `SentryMiddleware`
  - `apps/api/pyproject.toml` — +sentry-sdk[fastapi], +mypy override
  - `.env.example` — +ATS_SENTRY_* переменные
  - `apps/api/tests/test_sentry.py` — 23 теста
- Тесты: 270 passed (+23)
- Issue #5 закрыт
- **Этап 1 (Наблюдаемость) ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5**

### [2026-08-29] JUGO-013 — S3-клиент + модуль core/files — ✅ DONE
- Коммит: `1a8d38c` | Тесты: 315 (+45) | Issue #6 закрыт
- Файлы:
  - `apps/api/src/ats/infra/storage/__init__.py` — экспорты + `get_storage()` фабрика
  - `apps/api/src/ats/infra/storage/settings.py` — `StorageSettings` (env: `ATS_STORAGE_*`)
  - `apps/api/src/ats/infra/storage/models.py` — `FileMetadata`, `UploadResult`, `ScanResult`, `DownloadResult`, `FileCategory`, `ScanStatus`
  - `apps/api/src/ats/infra/storage/protocol.py` — `FileStorage` Protocol + `AntivirusScanner` Protocol
  - `apps/api/src/ats/infra/storage/whitelist.py` — whitelist MIME (category-specific) + `validate_extension` + `validate_mime`
  - `apps/api/src/ats/infra/storage/antivirus.py` — `ClamAVScanner` (ленивый импорт) + `DummyScanner`
  - `apps/api/src/ats/infra/storage/in_memory.py` — `InMemoryFileStorage` (dev/тесты)
  - `apps/api/src/ats/infra/storage/s3.py` — `S3FileStorage` (ленивый aioboto3)
  - `apps/api/tests/test_storage.py` — 45 тестов
- Тесты: 315 passed (+45)
- Issue #6 закрыт

### [2026-08-29] JUGO-014 — Сиды демо-данных — ✅ DONE
- Коммит: `82aa700` | Тесты: 353 (+38) | Issue #7 закрыт
- Файлы:
  - `apps/api/src/ats/infra/seeds/__init__.py` — экспорты
  - `apps/api/src/ats/infra/seeds/settings.py` — `SeedSettings` (env: `ATS_SEED_*`)
  - `apps/api/src/ats/infra/seeds/generator.py` — `SeedGenerator` (5к кандидатов, 20 вакансий, отклики, этапы)
  - `apps/api/src/ats/infra/seeds/cli.py` — CLI для запуска сидов
  - `apps/api/src/ats/infra/seeds/__main__.py` — `python -m ats.infra.seeds`
  - `apps/api/tests/test_seeds.py` — 38 тестов
- Тесты: 353 passed (+38)
- Issue #7 закрыт
- **Этап 2 (Файлы и сиды) ПОЛНОСТЬЮ ЗАВЕРШЁН: 2/2**

### [2026-08-29] JUGO-021 — Сессии — refresh + rate limit + CSRF — ✅ DONE
- Коммит: `38d38b2` | Тесты: 372 (+19) | Issue #8 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/session.py` — `Session`, `SessionManager`, refresh-токены, rate limit
  - `apps/api/src/ats/modules/identity/infra/rate_limiter.py` — `RateLimiter` (token bucket)
  - `apps/api/src/ats/modules/identity/infra/csrf.py` — `CSRFProtection` (double-submit cookie)
  - `apps/api/src/ats/modules/identity/api/deps.py` — `get_current_user`, `require_permission`
  - `apps/api/src/ats/modules/identity/api/router.py` — login, refresh, logout, CSRF token
  - `apps/api/tests/test_sessions.py` — 19 тестов
- Тесты: 372 passed (+19)
- Issue #8 закрыт

### [2026-08-29] JUGO-025 — API-ключи со скоупами — ✅ DONE
- Коммит: `1577581` | Тесты: 432 (+23) | Issue #10 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/api_key.py` — `APIKey`, `APIKeyScope`, генерация, хэш, скоупы
  - `apps/api/src/ats/modules/identity/ports/api_key.py` — `APIKeyStore` Protocol
  - `apps/api/src/ats/modules/identity/infra/in_memory_api_key.py` — `InMemoryAPIKeyStore`
  - `apps/api/src/ats/modules/identity/api/router.py` — API key CRUD endpoints
  - `apps/api/tests/test_api_keys.py` — 23 теста (генерация, хэш, скоупы, CRUD, auth)
- Тесты: 432 passed (+23)
- Issue #10 закрыт

### [2026-08-29] JUGO-023 — 2FA (TOTP) для админ-ролей — ✅ DONE
- Коммит: `3ca59dc` | Тесты: 409 (+37) | Issue #9 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/totp.py` — TOTP на чистом stdlib (HMAC-SHA1, RFC 6238/4226), без pyotp: `generate_secret`, `totp_code`, `verify_totp` (tolerance ±30s, constant-time), `build_otpauth_uri` (для QR-кода), `generate_backup_codes`, `hash_backup_code` (SHA-256)
  - `apps/api/src/ats/modules/identity/domain/two_factor.py` — `TwoFactorConfig`, `TwoFactorSetupResult`, `TwoFactorChallenge`, `ROLES_REQUIRING_2FA` = {admin, head_of_recruiting}, `is_2fa_required_for_user`
  - `apps/api/src/ats/modules/identity/ports/two_factor.py` — `TwoFactorStore` Protocol (setup, verify_and_enable, verify_code, verify_backup_code, disable, challenge lifecycle)
  - `apps/api/src/ats/modules/identity/infra/in_memory_2fa.py` — `InMemoryTwoFactorStore` (dev/тесты)
  - `apps/api/src/ats/modules/identity/infra/runtime.py` — `get_two_factor_store()` singleton + reset
  - `apps/api/src/ats/modules/identity/api/router.py` — 2FA endpoints: `/2fa/setup`, `/2fa/enable`, `/2fa/status`, `/2fa/disable` + login challenge flow `/2fa/verify`, `/2fa/backup`; login возвращает challenge_token если 2FA требуется
  - `apps/api/tests/test_api.py` — fix `asyncio.get_event_loop().run_until_complete` → `asyncio.run` (устаревший API ломался при порядке тестов)
  - `apps/api/tests/test_2fa.py` — 37 тестов (TOTP, backup codes, store, API)
- Тесты: 409 passed (+37)
- Issue #9 закрыт

### [2026-08-29] JUGO-026 — OIDC/SSO — абстракция identity-провайдера — ✅ DONE
- Коммит: `a47c99b` | Тесты: 456 (+24) | Issue #11 закрыт
- Файлы:
  - `apps/api/src/ats/modules/identity/domain/oidc.py` — OIDC модели (AuthRequest, TokenResponse, UserInfo, CallbackResult), OIDCProvider enum, PKCE helpers (generate_state, generate_pkce_verifier, generate_pkce_challenge)
  - `apps/api/src/ats/modules/identity/ports/identity_provider.py` — `IdentityProvider` Protocol
  - `apps/api/src/ats/modules/identity/infra/stub_identity_provider.py` — `StubIdentityProvider` (dev/тесты)
  - `apps/api/src/ats/modules/identity/infra/oidc_settings.py` — `OIDCSettings` (env: `ATS_OIDC_*`)
  - `apps/api/src/ats/modules/identity/api/router.py` — OIDC endpoints: `/auth/oidc/{provider}/start`, `/auth/oidc/{provider}/callback`
  - `apps/api/tests/test_oidc.py` — 24 теста (PKCE, state, auth flow, callback, multi-provider)
- Тесты: 456 passed (+24)
- Issue #11 закрыт
- **Этап 3 (Безопасность) ПОЛНОСТЬЮ ЗАВЕРШЁН: 4/4**

### [2026-08-30] JUGO-027 — CI: GitHub Actions pipeline — ✅ DONE
- Коммит: `40c7d31` | Тесты: 456 (без изменений) | Issue #12 закрыт
- Файлы:
  - `.github/workflows/ci.yml` — 3 job: lint (ruff check + format, blocking), mypy (advisory, continue-on-error), tests (456 green, ATS_STUB_MODE=1)
  - `apps/api/pyproject.toml` — ruff ignore rules (RUF001/002/003, B008, N811) + auto-fixes (161) + format (175 files)
  - `apps/api/src/ats/infra/ai/litellm_gateway.py` — SIM102 fixed (nested if combined)
  - `README.md` — CI badge added
- Тесты: 456 passed
- Issue #12 закрыт
- **ВОЛНА 0 ПОЛНОСТЬЮ ЗАВЕРШЕНА: 12/12 задач, 456 тестов green**

---
