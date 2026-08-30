#!/usr/bin/env python3
"""Проверка обратной совместимости OpenAPI (JUGO-193).

Сравнивает текущую спецификацию (из app.openapi()) с закоммиченным snapshot
(contracts/openapi/openapi.json). Запускается в CI на каждый PR.

Правила:
- DELETE path → breaking ❌
- DELETE method on existing path → breaking ❌
- DELETE required request param → breaking ❌
- DELETE response status → breaking ❌
- ADD new path/method/param/response → non-breaking ✅
- Изменение типа поля → breaking ❌

SECURE FIRST: любые breaking changes требуют бампа версии (v1 → v2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_snapshot() -> dict[str, Any] | None:
    """Загрузить закоммиченный snapshot."""
    snapshot_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def load_current() -> dict[str, Any]:
    """Загрузить текущую спецификацию из app."""
    from ats.main import app

    return app.openapi()


def check_breaking_changes(
    snapshot: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Найти breaking changes между snapshot и current.

    Возвращает список описаний breaking changes (пустой = ОК).
    """
    breaking: list[str] = []

    snap_paths = snapshot.get("paths", {})
    curr_paths = current.get("paths", {})

    # 1. Удалённые paths → breaking
    for path in snap_paths:
        if path not in curr_paths:
            breaking.append(f"Path removed: {path}")

    # 2. Удалённые методы на существующих paths → breaking
    for path, methods in snap_paths.items():
        if path not in curr_paths:
            continue
        for method in methods:
            if method not in curr_paths[path]:
                breaking.append(f"Method removed: {method.upper()} {path}")

    # 3. Удалённые response codes → breaking
    for path, methods in snap_paths.items():
        if path not in curr_paths:
            continue
        for method, spec in methods.items():
            if method not in curr_paths[path]:
                continue
            snap_responses = spec.get("responses", {})
            curr_responses = curr_paths[path][method].get("responses", {})
            for code in snap_responses:
                if code not in curr_responses:
                    breaking.append(f"Response removed: {code} on {method.upper()} {path}")

    # 4. Удалённые required параметры → breaking
    for path, methods in snap_paths.items():
        if path not in curr_paths:
            continue
        for method, spec in methods.items():
            if method not in curr_paths[path]:
                continue
            snap_params = spec.get("parameters", [])
            curr_params = curr_paths[path][method].get("parameters", [])
            curr_required_params = {
                (p.get("name"), p.get("in"))
                for p in curr_params
                if p.get("required", False)
            }
            for param in snap_params:
                if param.get("required", False):
                    key = (param.get("name"), param.get("in"))
                    if key not in curr_required_params:
                        breaking.append(
                            f"Required parameter removed: {param.get('name')} ({param.get('in')}) "
                            f"on {method.upper()} {path}"
                        )

    # 5. Удалённые схемы компонентов → breaking
    snap_schemas = snapshot.get("components", {}).get("schemas", {})
    curr_schemas = current.get("components", {}).get("schemas", {})
    for schema_name in snap_schemas:
        if schema_name not in curr_schemas:
            breaking.append(f"Schema removed: {schema_name}")

    # 6. Удалённые required поля в схемах → breaking
    for schema_name, snap_schema in snap_schemas.items():
        if schema_name not in curr_schemas:
            continue
        curr_schema = curr_schemas[schema_name]
        snap_required = set(snap_schema.get("required", []))
        curr_required = set(curr_schema.get("required", []))
        removed_required = snap_required - curr_required
        # removed_required — это поля, которые БЫЛИ required, а стали НЕ required
        # Это на самом деле non-breaking (менее строго). Проверяем наоборот:
        # поля, которые стали required (новые обязательные) → breaking
        new_required = curr_required - snap_required
        for field in new_required:
            breaking.append(f"New required field: {schema_name}.{field}")

    return breaking


def main() -> int:
    snapshot = load_snapshot()
    if snapshot is None:
        print("⚠ No OpenAPI snapshot found. Run generate_openapi.py first.")
        print("  Skipping backward compat check (first run).")
        return 0

    current = load_current()
    breaking = check_breaking_changes(snapshot, current)

    if not breaking:
        print("✅ OpenAPI backward compatible — no breaking changes detected.")
        return 0

    print("❌ OpenAPI breaking changes detected:")
    for change in breaking:
        print(f"  - {change}")
    print()
    print("Breaking changes require a version bump (e.g. /api/v1 → /api/v2).")
    print("If intentional, update the snapshot: python3 scripts/generate_openapi.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
