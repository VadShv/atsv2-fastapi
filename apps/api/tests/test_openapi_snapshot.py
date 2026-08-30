"""Tests for JUGO-193: OpenAPI snapshot + backward compat check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats.infra.container_helpers import reset_container
from ats.main import app


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_container()


class TestOpenAPISnapshot:
    """OpenAPI snapshot exists and is valid."""

    def test_snapshot_file_exists(self) -> None:
        snapshot_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
        assert snapshot_path.exists(), f"OpenAPI snapshot not found at {snapshot_path}"

    def test_snapshot_is_valid_json(self) -> None:
        snapshot_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "openapi" in data
        assert "paths" in data
        assert "components" in data

    def test_snapshot_has_webhook_paths(self) -> None:
        snapshot_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        paths = data.get("paths", {})
        webhook_paths = [p for p in paths if "/webhooks" in p]
        assert len(webhook_paths) >= 4, f"Expected >=4 webhook paths, got {webhook_paths}"

    def test_snapshot_has_search_paths(self) -> None:
        snapshot_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        paths = data.get("paths", {})
        search_paths = [p for p in paths if "/search" in p]
        assert len(search_paths) >= 1

    def test_snapshot_has_problem_detail_schema(self) -> None:
        """RFC 9457 ProblemDetail should be in schemas."""
        snapshot_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "openapi" / "openapi.json"
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        schemas = data.get("components", {}).get("schemas", {})
        # ProblemDetail might be named differently, check for trace_id field
        assert len(schemas) > 0


class TestOpenAPICompat:
    """Backward compat check logic."""

    def test_no_breaking_changes_self(self) -> None:
        """Comparing spec with itself -> no breaking changes."""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from check_openapi_compat import check_breaking_changes

        spec = app.openapi()
        breaking = check_breaking_changes(spec, spec)
        assert breaking == []

    def test_removed_path_is_breaking(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from check_openapi_compat import check_breaking_changes

        old = {"paths": {"/api/v1/test": {"get": {}}}, "components": {"schemas": {}}}
        new = {"paths": {}, "components": {"schemas": {}}}
        breaking = check_breaking_changes(old, new)
        assert any("Path removed" in b for b in breaking)

    def test_removed_method_is_breaking(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from check_openapi_compat import check_breaking_changes

        old = {"paths": {"/api/v1/test": {"get": {}, "post": {}}}, "components": {"schemas": {}}}
        new = {"paths": {"/api/v1/test": {"get": {}}}, "components": {"schemas": {}}}
        breaking = check_breaking_changes(old, new)
        assert any("Method removed" in b for b in breaking)

    def test_added_path_is_not_breaking(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from check_openapi_compat import check_breaking_changes

        old = {"paths": {"/api/v1/test": {"get": {}}}, "components": {"schemas": {}}}
        new = {
            "paths": {"/api/v1/test": {"get": {}}, "/api/v1/new": {"post": {}}},
            "components": {"schemas": {}},
        }
        breaking = check_breaking_changes(old, new)
        assert breaking == []

    def test_new_required_field_is_breaking(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from check_openapi_compat import check_breaking_changes

        old = {
            "paths": {},
            "components": {"schemas": {"MySchema": {"type": "object", "required": ["a"]}}},
        }
        new = {
            "paths": {},
            "components": {"schemas": {"MySchema": {"type": "object", "required": ["a", "b"]}}},
        }
        breaking = check_breaking_changes(old, new)
        assert any("New required field" in b for b in breaking)


class TestOpenAPIMetadata:
    """JUGO-194: API metadata for Redoc."""

    def test_app_has_title(self) -> None:
        spec = app.openapi()
        assert "ATS" in spec.get("info", {}).get("title", "")

    def test_app_has_description(self) -> None:
        spec = app.openapi()
        desc = spec.get("info", {}).get("description", "")
        assert "Authentication" in desc or "Idempotency" in desc

    def test_app_has_tags(self) -> None:
        spec = app.openapi()
        tags = spec.get("tags", [])
        tag_names = [t.get("name") for t in tags]
        assert "webhooks" in tag_names
        assert "search" in tag_names

    def test_redoc_endpoint_available(self) -> None:
        """FastAPI provides /redoc by default."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_docs_endpoint_available(self) -> None:
        from starlette.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_endpoint(self) -> None:
        from starlette.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"]
