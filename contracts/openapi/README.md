# contracts/openapi/ — REST API контракты

OpenAPI-спецификация генерируется из FastAPI-приложения (`apps/api/src/ats/main.py`).

## Генерация

```bash
cd apps/api
PYTHONPATH=src ATS_STUB_MODE=1 python3 -c "import json; from ats.main import app; print(json.dumps(app.openapi(), indent=2))" > ../../contracts/openapi/openapi.json
```

## Версионирование

- REST API версонируется префиксом: `/api/v1/...`.
- Breaking changes → бамп major версии префикса (`/api/v2/`).
- Контрактные тесты (`tests/contracts/`) фиксируют схемы ответов.
