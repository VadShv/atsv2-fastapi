#!/usr/bin/env python3
"""Генерация OpenAPI snapshot из FastAPI-приложения (JUGO-193).

Сохраняет актуальную OpenAPI-спецификацию в contracts/openapi/openapi.json.
Проверка обратной совместимости выполняется отдельным скриптом check_compat.py.

Запуск:
    cd apps/api
    PYTHONPATH=src ATS_STUB_MODE=1 python3 scripts/generate_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        from ats.main import app
    except ImportError as e:
        print(f"Error importing app: {e}", file=sys.stderr)
        return 1

    openapi_spec = app.openapi()

    # Путь: apps/api/scripts/ → ../../contracts/openapi/openapi.json
    output = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(json.dumps(openapi_spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OpenAPI snapshot written: {output}")
    print(f"  Paths: {len(openapi_spec.get('paths', {}))}")
    print(f"  Schemas: {len(openapi_spec.get('components', {}).get('schemas', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
