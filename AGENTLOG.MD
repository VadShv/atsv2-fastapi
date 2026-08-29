# AGENTLOG.MD — Журнал прогресса ATS Jugo

> Этот файл ведётся агентом (и человеком) для отслеживания состояния работ.
> После каждой завершённой задачи — добавляем запись в раздел «История».
> Формат: `[ДАТА] JUGO-XXX — статус — что сделано — файлы`.

---

## Текущий фокус: Волна 0 — Гейт

**Цель гейта:** пустое приложение с логином, ролями, аудитом, метриками и зелёным CI.

### Карта задач

| JUGO | Эпик | Описание | Статус | Issue |
|------|------|----------|--------|-------|
| JUGO-010 | E-01 | docker-compose (pg+pgvector, redis, api, web, worker) | ✅ DONE | — |
| JUGO-011 | E-01 | Alembic (миграции 0001–0007) | ✅ DONE | — |
| JUGO-012 | E-01 | Каркас воркеров arq (5 очередей, BaseTask) | ✅ DONE | — |
| JUGO-013 | E-01 | S3-клиент + модуль core/files | ⬜ TODO | #6 |
| JUGO-014 | E-01 | Сиды демо-данных (5к кандидатов, 20 вакансий) | ⬜ TODO | #7 |
| JUGO-020 | E-02 | Модель users/roles/permissions + скоупы | ✅ DONE | — |
| JUGO-021 | E-02 | Сессии — refresh + rate limit + CSRF | 🔶 PARTIAL | #8 |
| JUGO-022 | E-02 | Permission-чекер deny-by-default | ✅ DONE | — |
| JUGO-023 | E-02 | 2FA (TOTP) для админ-ролей | ⬜ TODO | #9 |
| JUGO-025 | E-02 | API-ключи со скоупами | ⬜ TODO | #10 |
| JUGO-026 | E-02 | OIDC/SSO — абстракция identity-провайдера | ⬜ TODO | #11 |
| JUGO-030 | E-03 | OpenTelemetry — трейсы, trace_id, Jaeger | ✅ DONE | #1 (closed) |
| JUGO-031 | E-03 | Prometheus-метрики — RPS, латентности, очереди | ✅ DONE | #2 (closed) |
| JUGO-032 | E-03 | Структурные JSON-логи + маскирование ПД | ✅ DONE | #3 (closed) |
| JUGO-033 | E-03 | audit_log — партиционирование + хелпер чтений | ✅ DONE | #4 (closed) |
| JUGO-034 | E-03 | Sentry + алерты | ✅ DONE | #5 (closed) |
| CI | — | GitHub Actions (lint + mypy + tests) | ⬜ TODO | #12 |

### Легенда
- ✅ DONE — полностью реализовано, тесты green
- 🔶 PARTIAL — часть реализована, нужно доработать
- ⬜ TODO — не начато
- 🚧 IN PROGRESS — в работе

### Порядок реализации (приоритет)

**Этап 1 — Наблюдаемость (E-03):** ✅ 5/5 ЗАВЕРШЁН
**Этап 2 — Файлы и сиды (E-01):** JUGO-013 → JUGO-014
**Этап 3 — Безопасность (E-02):** JUGO-021 → JUGO-023 → JUGO-025 → JUGO-026
**Этап 4 — CI:** GitHub Actions pipeline

### Прогресс

| Этап | Задач | Готово | Тестов |
|------|-------|--------|--------|
| 1. Наблюдаемость (E-03) | 5 | 5/5 ✅ | 270 |
| 2. Файлы и сиды (E-01) | 2 | 0/2 | — |
| 3. Безопасность (E-02) | 4 | 0/4 | — |
| 4. CI | 1 | 0/1 | — |
| **Итого** | **12** | **5/12** | **270** |

### Этап 1 — Детализация

| Задача | Тестов | Коммит |
|--------|--------|--------|
| JUGO-032 (Логи + PII) | +27 | `69c1dc4` |
| JUGO-030 (OTel) | +29 | `fbfb504` |
| JUGO-031 (Prometheus) | +28 | `9e2dd0d` |
| JUGO-033 (Audit partition) | +24 | `eba7513` |
| JUGO-034 (Sentry + alerts) | +23 | `f8a1915` |
| **Итого Этап 1** | **+131** | |

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
- ✅ Доменные события обогащены под контракты
- ✅ Audit Log: domain, ports, in-memory + pg логгер, миграция 0005
- ✅ Auth + RBAC: rbac.py, session.py, deps.py, router, 7 ролей
- ✅ Cloud.ru + embedding 4096: gateway api_base/api_key, миграция 0006 (halfvec+HNSW)
- ✅ Каркас воркеров arq (JUGO-012): 5 очередей, BaseTask, дедупликация, CLI
- 144 теста green, деплой на 176.108.250.112

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
  - `apps/api/src/ats/main.py` — подключён `setup_sentry()` + `SentryMiddleware`
  - `apps/api/pyproject.toml` — +sentry-sdk[fastapi], +mypy override
  - `.env.example` — +ATS_SENTRY_* переменные
  - `apps/api/tests/test_sentry.py` — 23 теста
- Тесты: 270 passed (+23)
- Issue #5 закрыт
- **Этап 1 (Наблюдаемость) ПОЛНОСТЬЮ ЗАВЕРШЁН: 5/5**

---
