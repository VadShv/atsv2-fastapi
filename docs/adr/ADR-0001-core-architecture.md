# ADR-0001: Архитектура ядра ATS

**Status:** Accepted
**Date:** 2026-08-29

## Контекст

Создаём новую AI-native ATS. Функциональный референс — Huntflow. Ядро должно отвечать
принципам: AI NATIVE, WHITEBOX AI, SECURE FIRST, УСТОЙЧИВОСТЬ, ДОСТУПНОСТЬ, USERFRIENDLY,
СКОРОСТЬ, БЫСТРЕЙШИЙ ПОИСК.

## Решение

### Архитектурный стиль

Модульный монолит + Ports & Adapters (гексагонал). Модули изолированы и общаются через
доменные события по in-process шине. Это даёт скорость разработки и целостность
транзакций монолита, изоляцию модулей и возможность вытаскивать их в микросервисы позже.

### Слои (зависимости внутрь)

```
api → application → domain ← ports
                        ↑
                   infrastructure (implements ports)
```

- `domain/` — сущности, value objects, инварианты, доменные события. Без зависимостей.
- `application/` — use cases (commands/queries).
- `ports/` — интерфейсы внешнего мира.
- `infrastructure/` — реализации адаптеров.
- `api/` — HTTP-слой.

### Bounded contexts (модули)

| Модуль | Ответственность |
|--------|-----------------|
| `identity` | users, auth, RBAC+ABAC, tenants |
| `recruitment` | вакансии, заявки, pipeline stages, transitions |
| `candidates` | candidate 360, документы, активити |
| `ai_core` | AIGateway, prompt registry, provenance ledger, AI skills |
| `search` | индексация, гибридный поиск, ранжирование |
| `audit` | audit log, consent, retention, PII-vault |

### Ключевые абстракции

#### AIGateway (порт)

Единая точка входа ко всем LLM. Скрыт за интерфейсом `AIGateway`, чтобы домен не зависел
от конкретного провайдера. Реализация — `LiteLLMGateway` с роутингом, retry/fallback,
семантическим кэшем, метриками и бюджетами.

```python
class AIGateway(Protocol):
    async def complete(self, request: AIRequest) -> AIResponse: ...
    async def stream(self, request: AIRequest) -> AsyncIterator[AIChunk]: ...
    async def structured(self, request: AIRequest, schema: type[T]) -> T: ...
```

#### Provenance Ledger

Каждый AI-артефакт хранит:
`{model, prompt_id, prompt_version, input_hash, input_refs, raw_output, parsed_output,
confidence, latency_ms, cost_usd, tokens_in, tokens_out, timestamp, human_verified,
reasoning_trace}`.

AI-артефакт в домене (напр. `ScreeningCriteria`) ссылается на `provenance_id`, что
обеспечивает whitebox: любой вывод можно объяснить и воспроизвести.

#### Prompt Registry

Промпты — код. Версионные, в `modules/ai_core/prompts/`. Каждый промпт:
`{id, version, template, schema, model_hint, temperature, system, variables}`.
Меняются через PR с ревью. Версия фиксиуется в provenance.

#### AI Skills

Композируемые use cases. Skill = доменный use case, использующий AIGateway.
Например: `GenerateScreeningCriteria`, `ParseResume`, `ScoreCandidate`, `MatchCandidate`.

#### SearchEngine (порт)

Гибридный поиск за интерфейсом. Реализация по умолчанию — `PgVectorSearchEngine`.

```python
class SearchEngine(Protocol):
    async def index(self, doc: SearchDocument) -> None: ...
    async def search(self, query: SearchQuery) -> SearchResults: ...
```

Запрос: BM25 (лексика) ⊕ vector (семантика) ⊕ metadata-фильтры → re-rank → фасеты.
Инкрементальная индексация из outbox-событий.

### Устойчивость

- **Outbox**: событие пишется в ту же транзакцию, что и агрегат. Воркер вычитывает и
  диспетчит. Гарантия at-least-once → обработчики идемпотентны.
- **Идемпотентность**: команды принимают `IdempotencyKey`.
- **Graceful degradation**: AI недоступен → fallback на детерминированную логику с
  пометкой `non_ai` + запись в provenance.
- **Бюджеты**: tenant-бюджеты токенов/стоимости против runaway.

### Безопасность

- RLS на уровне Postgres: каждый запрос с `SET app.tenant_id`.
- PII-vault: ФИО/контакты шифруются, в БД — токены.
- RBAC + ABAC: роли + политики доступа.
- Append-only audit log.
- Секреты из env.

## Фаза старта: AI-генерация критериев скрининга

Ключевая фича старта: **при создании вакансии, после ввода описания роли, ИИ
генерирует критерии скрининга**.

Поток:
1. Рекрутер создаёт вакансию → `CreateVacancy` (описание роли + метаданные).
2. Агрегат `Vacancy` создаётся, публикуется `VacancyCreated`.
3. Воркер/синхронный use case `GenerateScreeningCriteria` реагирует:
   - Собирает контекст: описание роли, стек, уровень, требования.
   - Вызывает `AIGateway.structured(...)` с промптом `screening_criteria:v1`.
   - Получает структурированные критерии (hard skills, soft skills, опыт, образование,
     red flags, веса).
   - Пишет provenance-запись.
   - Сохраняет `ScreeningCriteria`, привязанные к `Vacancy`.
   - Публикует `ScreeningCriteriaGenerated`.
4. Фронт получает критерии (streaming или polling) → inline accept/reject.
5. Критерии используются в дальнейшем скрининге кандидатов.

## Последствия

- Изоляция модулей требует дисциплины в публичных интерфейсах.
- Outbox добавляет таблицу + воркер, но даёт надёжность.
- Provenance добавляет хранение, но даёт whitebox и аудит.
- Гексагонал добавляет слой интерфейсов, но даёт тестируемость и смену адаптеров.
