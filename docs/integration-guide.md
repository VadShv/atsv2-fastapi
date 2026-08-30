# Integration Guide — ATS Jugo API

> Первая интеграция за 15 минут.

## 1. Аутентификация

Все запросы требуют API-ключ. Передайте его в заголовке `X-API-Key`:

```bash
curl -H "X-API-Key: jugo_live_your_key_here" \
     -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
     https://your-ats-host/api/v1/candidates
```

API-ключи создаются в админ-панели (или через `POST /api/v1/auth/api-keys`).
Ключ показывается один раз — сохраните его.

## 2. Создание вакансии

```bash
curl -X POST https://your-ats-host/api/v1/vacancies \
  -H "X-API-Key: jugo_live_..." \
  -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
  -H "Idempotency-Key: my-unique-key-001" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Developer",
    "description": "We are looking for...",
    "department": "Backend",
    "employment_type": "full_time"
  }'
```

`Idempotency-Key` гарантирует, что повторный запрос с тем же ключом не создаст
дубликат. Кэш действителен 24 часа.

## 3. Поиск кандидатов

Гибридный поиск: BM25 (текст) + векторный (семантика).

```bash
curl -X POST https://your-ats-host/api/v1/search/candidates \
  -H "X-API-Key: jugo_live_..." \
  -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "python AND (senior OR lead) NOT junior",
    "limit": 20
  }'
```

Булевы операторы: `AND`, `OR`, `NOT`, кавычки для фраз `"python developer"`,
скобки для группировки. Plain-запросы (без операторов) используют OR-семантику
для максимального recall.

## 4. Создание отклика

```bash
curl -X POST https://your-ats-host/api/v1/applications \
  -H "X-API-Key: jugo_live_..." \
  -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
  -H "Idempotency-Key: app-creation-001" \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_id": "...",
    "vacancy_id": "..."
  }'
```

## 5. Вебхуки

Подпишитесь на события, чтобы получать уведомления:

```bash
curl -X POST https://your-ats-host/api/v1/webhooks \
  -H "X-API-Key: jugo_live_..." \
  -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.com/webhooks/ats",
    "events": ["application.created", "application.rejected", "*"]
  }'
```

Ответ содержит `secret` — сохраните его. Каждый вебхук подписывается:

**Заголовок:** `X-Jugo-Signature: t=<timestamp>,sha256=<hmac>`

**Проверка на вашей стороне:**

```python
import hmac, hashlib

def verify_webhook(body: bytes, signature_header: str, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in signature_header.split(","))
    ts = parts["t"]
    sig = parts["sha256"]
    expected = hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)
```

Ретраи доставки: 1м → 5м → 30м → 2ч → 6ч. После исчерпания подписка помечается
`degraded`. Журнал доставок: `GET /api/v1/webhooks/{id}/deliveries`.

Тестовая отправка: `POST /api/v1/webhooks/{id}/test`.

## 6. Rate Limiting

| Тип | Лимит | Заголовки |
|-----|-------|-----------|
| Чтение (GET) | 600 rpm | `X-RateLimit-Remaining`, `X-RateLimit-Reset` |
| Запись (POST/PUT/PATCH/DELETE) | 120 rpm | `X-RateLimit-Remaining`, `X-RateLimit-Reset` |

При превышении: `429 Too Many Requests` + заголовок `Retry-After`.

## 7. Обработка ошибок

Все ошибки возвращаются в формате RFC 9457 (`application/problem+json`):

```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 422,
  "detail": "One or more fields failed validation",
  "errors": [
    {"field": "email", "code": "invalid_format", "message": "Not a valid email"}
  ],
  "trace_id": "a1b2c3d4..."
}
```

Используйте `trace_id` для обращения в поддержку.

## 8. Документация API

- **Swagger UI**: `GET /docs` — интерактивная документация
- **ReDoc**: `GET /redoc` — чистая читаемая документация
- **OpenAPI JSON**: `GET /openapi.json` — машиночитаемая спецификация
