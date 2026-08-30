"""Tests for JUGO-200 API: /org endpoints (legal entities + org units)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.main import app


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_container()


class TestLegalEntityAPI:
    def test_list_empty(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/org/legal-entities")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_get(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/org/legal-entities",
            json={"name": "ООО Тест", "type": "ooo", "inn": "1234567890"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "ООО Тест"
        assert body["type"] == "ooo"
        assert body["inn"] == "1234567890"
        le_id = body["id"]

        # Get
        resp = client.get(f"/api/v1/org/legal-entities/{le_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "ООО Тест"

    def test_create_duplicate_conflict(self) -> None:
        client = TestClient(app)
        client.post("/api/v1/org/legal-entities", json={"name": "Dup"})
        resp = client.post("/api/v1/org/legal-entities", json={"name": "Dup"})
        assert resp.status_code == 400
        assert "problem" in resp.headers.get("content-type", "")

    def test_get_not_found(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/org/legal-entities/00000000-0000-0000-0000-000000000099")
        assert resp.status_code == 404

    def test_update(self) -> None:
        client = TestClient(app)
        create = client.post("/api/v1/org/legal-entities", json={"name": "Old"})
        le_id = create.json()["id"]
        resp = client.patch(
            f"/api/v1/org/legal-entities/{le_id}",
            json={"name": "New", "inn": "999"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"
        assert resp.json()["inn"] == "999"

    def test_archive(self) -> None:
        client = TestClient(app)
        create = client.post("/api/v1/org/legal-entities", json={"name": "ToArchive"})
        le_id = create.json()["id"]
        resp = client.delete(f"/api/v1/org/legal-entities/{le_id}")
        assert resp.status_code == 204

        # Archived — not in default list
        resp = client.get("/api/v1/org/legal-entities")
        assert resp.status_code == 200
        assert all(e["name"] != "ToArchive" for e in resp.json())

        # Include archived
        resp = client.get("/api/v1/org/legal-entities?include_archived=true")
        assert any(e["name"] == "ToArchive" for e in resp.json())

    def test_invalid_type(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/org/legal-entities",
            json={"name": "Test", "type": "invalid_type"},
        )
        assert resp.status_code == 400


class TestOrgUnitAPI:
    def test_create_root_unit(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        resp = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Engineering"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Engineering"
        assert body["parent_id"] is None
        assert body["path"]

    def test_create_child_unit(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Engineering"},
        ).json()
        resp = client.post(
            "/api/v1/org/units",
            json={
                "legal_entity_id": le["id"],
                "name": "Backend",
                "parent_id": root["id"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["parent_id"] == root["id"]
        assert body["path"].startswith(root["path"])

    def test_list_root_units(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Root1"},
        )
        root2 = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Root2"},
        ).json()
        client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Child", "parent_id": root2["id"]},
        )

        resp = client.get(f"/api/v1/org/legal-entities/{le['id']}/units")
        assert resp.status_code == 200
        names = [u["name"] for u in resp.json()]
        assert "Root1" in names
        assert "Root2" in names
        assert "Child" not in names

    def test_get_subtree(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Root"},
        ).json()
        child = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Child", "parent_id": root["id"]},
        ).json()
        client.post(
            "/api/v1/org/units",
            json={
                "legal_entity_id": le["id"],
                "name": "Grandchild",
                "parent_id": child["id"],
            },
        )
        other = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Other"},
        ).json()

        resp = client.get(f"/api/v1/org/units/{root['id']}/subtree")
        assert resp.status_code == 200
        names = [u["name"] for u in resp.json()]
        assert "Root" in names
        assert "Child" in names
        assert "Grandchild" in names
        assert "Other" not in names

    def test_list_children(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Root"},
        ).json()
        client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "C1", "parent_id": root["id"]},
        )
        client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "C2", "parent_id": root["id"]},
        )

        resp = client.get(f"/api/v1/org/units/{root['id']}/children")
        assert resp.status_code == 200
        names = [u["name"] for u in resp.json()]
        assert set(names) == {"C1", "C2"}

    def test_archive_with_children_blocked(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Root"},
        ).json()
        client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Child", "parent_id": root["id"]},
        )
        resp = client.delete(f"/api/v1/org/units/{root['id']}")
        assert resp.status_code == 400

    def test_move_unit(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        old_root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "OldRoot"},
        ).json()
        child = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Child", "parent_id": old_root["id"]},
        ).json()
        new_root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "NewRoot"},
        ).json()

        resp = client.post(
            f"/api/v1/org/units/{child['id']}/move",
            json={"new_parent_id": new_root["id"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_id"] == new_root["id"]
        assert body["path"].startswith(new_root["path"])

    def test_move_creates_cycle_blocked(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        root = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Root"},
        ).json()
        child = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "Child", "parent_id": root["id"]},
        ).json()
        grandchild = client.post(
            "/api/v1/org/units",
            json={
                "legal_entity_id": le["id"],
                "name": "GC",
                "parent_id": child["id"],
            },
        ).json()

        resp = client.post(
            f"/api/v1/org/units/{root['id']}/move",
            json={"new_parent_id": grandchild["id"]},
        )
        assert resp.status_code == 409

    def test_get_unit_not_found(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/org/units/00000000-0000-0000-0000-000000000099")
        assert resp.status_code == 404

    def test_update_unit(self) -> None:
        client = TestClient(app)
        le = client.post(
            "/api/v1/org/legal-entities", json={"name": "LE"}
        ).json()
        unit = client.post(
            "/api/v1/org/units",
            json={"legal_entity_id": le["id"], "name": "OldName"},
        ).json()
        resp = client.patch(
            f"/api/v1/org/units/{unit['id']}",
            json={"name": "NewName"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "NewName"
