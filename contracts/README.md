# contracts/ — Контракты ATS Jugo

Замороженные контракты системы. Изменения — только через RFC + бамп `schema_version`.

## Структура

```
contracts/
  events/        JSON Schemas событий v1 (контракт §4.3 ТЗ)
  openapi/       OpenAPI-спецификация REST API
  prompts/       Контракты AI-промптов (id, version, input/output schema)
```

## Принципы (ТЗ §4.3, §3.1)

- **Версионируемость**: каждое событие имеет `event_type` + `schema_version`. Изменения — только обратно совместимые расширения, потом миграция потребителей, потом новая версия.
- **Контрактные тесты**: `tests/contracts/` проверяют, что событие из кода валидно по схеме.
- **Модульность**: модули общаются только через события; контракт события — точка стыковки.

## Конверт события (envelope)

Все события оборачиваются в единый конверт (см. `events/envelope.schema.json`):

```json
{
  "event_id": "0192...",
  "event_type": "application.stage.changed",
  "schema_version": 1,
  "occurred_at": "2026-08-29T12:00:00Z",
  "tenant_id": "uuid",
  "actor": {"type": "user", "id": "uuid"},
  "aggregate": {"type": "application", "id": "uuid"},
  "payload": { ... }
}
```

## Топики Redis Streams

- `events:core` — доменные события ядра (candidate, vacancy, application, funnel)
- `events:ai` — AI-события (screening, risk, questions, ai.run.*)
