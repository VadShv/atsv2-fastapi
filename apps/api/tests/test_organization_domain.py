"""Tests for JUGO-200: Organization — domain, use cases, tree operations."""

from __future__ import annotations

import pytest

from ats.infra.stubs_org import InMemoryLegalEntityRepository, InMemoryOrgUnitRepository
from ats.modules.organization.application.org_use_cases import (
    LegalEntityUseCase,
    OrgUnitUseCase,
)
from ats.modules.organization.domain import (
    CycleDetectedError,
    LegalEntity,
    LegalEntityType,
    OrgUnit,
)
from ats.shared.ids import TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Domain: LegalEntity
# ---------------------------------------------------------------------------


class TestLegalEntityDomain:
    def test_create_legal_entity(self) -> None:
        le = LegalEntity.create(TENANT, name="ООО Ромашка", type=LegalEntityType.OOO, inn="12345")
        assert le.name == "ООО Ромашка"
        assert le.type == LegalEntityType.OOO
        assert le.inn == "12345"
        assert le.is_archived is False
        assert len(le._events) == 1

    def test_create_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="не может быть пустым"):
            LegalEntity.create(TENANT, name="  ")

    def test_full_name_defaults_to_name(self) -> None:
        le = LegalEntity.create(TENANT, name="Test Inc")
        assert le.full_name == "Test Inc"

    def test_update_legal_entity(self) -> None:
        le = LegalEntity.create(TENANT, name="Old Name")
        le.update(name="New Name", inn="99999")
        assert le.name == "New Name"
        assert le.inn == "99999"
        assert len(le._events) == 2

    def test_update_empty_name_raises(self) -> None:
        le = LegalEntity.create(TENANT, name="Name")
        with pytest.raises(ValueError, match="не может быть пустым"):
            le.update(name="")

    def test_archive_legal_entity(self) -> None:
        le = LegalEntity.create(TENANT, name="To Archive")
        le.archive()
        assert le.is_archived is True
        assert len(le._events) == 2

    def test_archive_is_idempotent(self) -> None:
        le = LegalEntity.create(TENANT, name="To Archive")
        le.archive()
        le.archive()
        assert le.is_archived is True
        assert len(le._events) == 2


# ---------------------------------------------------------------------------
# Domain: OrgUnit
# ---------------------------------------------------------------------------


class TestOrgUnitDomain:
    def test_create_root_unit(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        unit = OrgUnit.create(
            tenant_id=TENANT,
            legal_entity_id=le.id,
            name="Engineering",
        )
        assert unit.parent_id is None
        assert unit.path == str(unit.id).replace("-", "_")
        assert unit.legal_entity_id == le.id

    def test_create_child_unit(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        parent = OrgUnit.create(TENANT, le.id, name="Engineering")
        child = OrgUnit.create(
            tenant_id=TENANT,
            legal_entity_id=le.id,
            name="Backend",
            parent_id=parent.id,
            parent_path=parent.path,
        )
        assert child.parent_id == parent.id
        assert child.path == f"{parent.path}.{str(child.id).replace('-', '_')}"

    def test_create_empty_name_raises(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        with pytest.raises(ValueError, match="не может быть пустым"):
            OrgUnit.create(TENANT, le.id, name="")

    def test_create_child_without_parent_path_raises(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        parent = OrgUnit.create(TENANT, le.id, name="Parent")
        with pytest.raises(ValueError, match="parent_path обязателен"):
            OrgUnit.create(
                tenant_id=TENANT,
                legal_entity_id=le.id,
                name="Child",
                parent_id=parent.id,
                parent_path="",
            )

    def test_update_org_unit(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        unit = OrgUnit.create(TENANT, le.id, name="Old")
        unit.update(name="New")
        assert unit.name == "New"

    def test_archive_org_unit(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        unit = OrgUnit.create(TENANT, le.id, name="Unit")
        unit.archive()
        assert unit.is_archived is True

    def test_move_to_root(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        parent = OrgUnit.create(TENANT, le.id, name="Parent")
        child = OrgUnit.create(TENANT, le.id, name="Child", parent_id=parent.id, parent_path=parent.path)
        # Move child to root
        new_path = child.move(new_parent_id=None, new_parent_path="")
        assert child.parent_id is None
        assert new_path == str(child.id).replace("-", "_")

    def test_move_to_new_parent(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        root = OrgUnit.create(TENANT, le.id, name="Root")
        child = OrgUnit.create(TENANT, le.id, name="Child", parent_id=root.id, parent_path=root.path)
        new_parent = OrgUnit.create(TENANT, le.id, name="NewParent")
        new_path = child.move(
            new_parent_id=new_parent.id,
            new_parent_path=new_parent.path,
        )
        assert child.parent_id == new_parent.id
        assert new_path == f"{new_parent.path}.{str(child.id).replace('-', '_')}"

    def test_move_under_descendant_raises_cycle(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        root = OrgUnit.create(TENANT, le.id, name="Root")
        child = OrgUnit.create(TENANT, le.id, name="Child", parent_id=root.id, parent_path=root.path)
        grandchild = OrgUnit.create(
            TENANT, le.id, name="Grandchild", parent_id=child.id, parent_path=child.path
        )
        # Trying to move root under grandchild → cycle
        with pytest.raises(CycleDetectedError):
            root.move(
                new_parent_id=grandchild.id,
                new_parent_path=grandchild.path,
                descendant_paths={child.path, grandchild.path},
            )

    def test_move_under_self_raises_cycle(self) -> None:
        le = LegalEntity.create(TENANT, name="LE")
        unit = OrgUnit.create(TENANT, le.id, name="Unit")
        with pytest.raises(CycleDetectedError):
            unit.move(
                new_parent_id=unit.id,
                new_parent_path=unit.path,
                descendant_paths=set(),
            )


# ---------------------------------------------------------------------------
# Use cases: LegalEntity
# ---------------------------------------------------------------------------


class TestLegalEntityUseCase:
    @pytest.fixture
    def use_case(self) -> LegalEntityUseCase:
        return LegalEntityUseCase(InMemoryLegalEntityRepository())

    async def test_create_and_get(self, use_case: LegalEntityUseCase) -> None:
        result = await use_case.create(TENANT, name="Test LLC", type=LegalEntityType.LLC)
        assert not is_error(result)
        le = result.value
        fetched = await use_case.get(TENANT, str(le.id))
        assert not is_error(fetched)
        assert fetched.value.name == "Test LLC"

    async def test_duplicate_name_conflict(self, use_case: LegalEntityUseCase) -> None:
        await use_case.create(TENANT, name="Dup")
        result = await use_case.create(TENANT, name="Dup")
        assert is_error(result)
        assert result.error.code.value == "conflict"

    async def test_get_not_found(self, use_case: LegalEntityUseCase) -> None:
        import uuid

        result = await use_case.get(TENANT, str(uuid.uuid4()))
        assert is_error(result)
        assert result.error.code.value == "not_found"

    async def test_update(self, use_case: LegalEntityUseCase) -> None:
        result = await use_case.create(TENANT, name="Old")
        le = result.value
        updated = await use_case.update(TENANT, str(le.id), name="New", inn="123")
        assert not is_error(updated)
        assert updated.value.name == "New"
        assert updated.value.inn == "123"

    async def test_update_archived_blocked(self, use_case: LegalEntityUseCase) -> None:
        result = await use_case.create(TENANT, name="LE")
        le = result.value
        await use_case.archive(TENANT, str(le.id))
        updated = await use_case.update(TENANT, str(le.id), name="New")
        assert is_error(updated)
        assert updated.error.code.value == "conflict"

    async def test_list_all_excludes_archived(self, use_case: LegalEntityUseCase) -> None:
        r1 = await use_case.create(TENANT, name="Active")
        r2 = await use_case.create(TENANT, name="ToArchive")
        await use_case.archive(TENANT, str(r2.value.id))
        entities = await use_case.list_all(TENANT)
        names = [e.name for e in entities]
        assert "Active" in names
        assert "ToArchive" not in names

    async def test_list_all_includes_archived(self, use_case: LegalEntityUseCase) -> None:
        r1 = await use_case.create(TENANT, name="Active")
        r2 = await use_case.create(TENANT, name="ToArchive")
        await use_case.archive(TENANT, str(r2.value.id))
        entities = await use_case.list_all(TENANT, include_archived=True)
        names = [e.name for e in entities]
        assert "Active" in names
        assert "ToArchive" in names

    async def test_update_name_conflict(self, use_case: LegalEntityUseCase) -> None:
        await use_case.create(TENANT, name="Name1")
        r2 = await use_case.create(TENANT, name="Name2")
        result = await use_case.update(TENANT, str(r2.value.id), name="Name1")
        assert is_error(result)
        assert result.error.code.value == "conflict"


# ---------------------------------------------------------------------------
# Use cases: OrgUnit (tree operations)
# ---------------------------------------------------------------------------


class TestOrgUnitUseCase:
    @pytest.fixture
    def repos(self) -> tuple:
        le_repo = InMemoryLegalEntityRepository()
        org_repo = InMemoryOrgUnitRepository()
        return le_repo, org_repo

    @pytest.fixture
    def use_case(self, repos: tuple) -> OrgUnitUseCase:
        le_repo, org_repo = repos
        return OrgUnitUseCase(org_repo, le_repo)

    async def test_create_root_unit(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        result = await use_case.create(TENANT, str(le.id), name="Engineering")
        assert not is_error(result)
        assert result.value.parent_id is None

    async def test_create_child_unit(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Engineering")).value
        child = (
            await use_case.create(
                TENANT, str(le.id), name="Backend", parent_id=str(root.id)
            )
        ).value
        assert child.parent_id == root.id
        assert child.path.startswith(root.path)

    async def test_create_unit_in_archived_le_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = LegalEntity.create(TENANT, name="LE")
        le.archive()
        await le_repo.save(le)
        result = await use_case.create(TENANT, str(le.id), name="Unit")
        assert is_error(result)
        assert result.error.code.value == "conflict"

    async def test_create_under_archived_parent_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Root")).value
        await use_case.archive(TENANT, str(root.id))
        result = await use_case.create(
            TENANT, str(le.id), name="Child", parent_id=str(root.id)
        )
        assert is_error(result)
        assert result.error.code.value == "conflict"

    async def test_create_cross_legal_entity_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le1 = await le_repo.save(LegalEntity.create(TENANT, name="LE1"))
        le2 = await le_repo.save(LegalEntity.create(TENANT, name="LE2"))
        root_in_le1 = (await use_case.create(TENANT, str(le1.id), name="Root1")).value
        result = await use_case.create(
            TENANT, str(le2.id), name="Child", parent_id=str(root_in_le1.id)
        )
        assert is_error(result)
        assert result.error.code.value == "validation"

    async def test_archive_with_active_children_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Root")).value
        await use_case.create(TENANT, str(le.id), name="Child", parent_id=str(root.id))
        result = await use_case.archive(TENANT, str(root.id))
        assert is_error(result)
        assert result.error.code.value == "conflict"

    async def test_archive_after_children_archived(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Root")).value
        child = (await use_case.create(TENANT, str(le.id), name="Child", parent_id=str(root.id))).value
        await use_case.archive(TENANT, str(child.id))
        result = await use_case.archive(TENANT, str(root.id))
        assert not is_error(result)

    async def test_move_with_descendant_path_update(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        old_root = (await use_case.create(TENANT, str(le.id), name="OldRoot")).value
        child = (
            await use_case.create(TENANT, str(le.id), name="Child", parent_id=str(old_root.id))
        ).value
        grandchild = (
            await use_case.create(
                TENANT, str(le.id), name="Grandchild", parent_id=str(child.id)
            )
        ).value
        new_root = (await use_case.create(TENANT, str(le.id), name="NewRoot")).value

        old_child_path = child.path
        old_grandchild_path = grandchild.path

        # Move child under new_root
        result = await use_case.move(TENANT, str(child.id), str(new_root.id))
        assert not is_error(result)
        moved = result.value

        # child path should now be under new_root
        assert moved.path.startswith(new_root.path)

        # Verify descendants were updated via repo
        _, org_repo = repos
        updated_grandchild = await org_repo.get_by_id(TENANT, str(grandchild.id))
        assert updated_grandchild is not None
        assert updated_grandchild.path.startswith(moved.path)
        assert updated_grandchild.path != old_grandchild_path

    async def test_move_creates_cycle_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Root")).value
        child = (await use_case.create(TENANT, str(le.id), name="Child", parent_id=str(root.id))).value
        grandchild = (
            await use_case.create(TENANT, str(le.id), name="GC", parent_id=str(child.id))
        ).value

        # Move root under grandchild → should fail
        result = await use_case.move(TENANT, str(root.id), str(grandchild.id))
        assert is_error(result)
        assert result.error.code.value == "conflict"

    async def test_move_to_self_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        unit = (await use_case.create(TENANT, str(le.id), name="Unit")).value
        result = await use_case.move(TENANT, str(unit.id), str(unit.id))
        assert is_error(result)

    async def test_move_cross_legal_entity_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le1 = await le_repo.save(LegalEntity.create(TENANT, name="LE1"))
        le2 = await le_repo.save(LegalEntity.create(TENANT, name="LE2"))
        unit1 = (await use_case.create(TENANT, str(le1.id), name="U1")).value
        unit2 = (await use_case.create(TENANT, str(le2.id), name="U2")).value
        result = await use_case.move(TENANT, str(unit1.id), str(unit2.id))
        assert is_error(result)
        assert result.error.code.value == "validation"

    async def test_get_subtree(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Root")).value
        child = (await use_case.create(TENANT, str(le.id), name="Child", parent_id=str(root.id))).value
        grandchild = (
            await use_case.create(TENANT, str(le.id), name="GC", parent_id=str(child.id))
        ).value
        other = (await use_case.create(TENANT, str(le.id), name="Other")).value

        result = await use_case.get_subtree(TENANT, str(root.id))
        assert not is_error(result)
        ids = {u.id for u in result.value}
        assert root.id in ids
        assert child.id in ids
        assert grandchild.id in ids
        assert other.id not in ids

    async def test_list_children(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root = (await use_case.create(TENANT, str(le.id), name="Root")).value
        c1 = (await use_case.create(TENANT, str(le.id), name="C1", parent_id=str(root.id))).value
        c2 = (await use_case.create(TENANT, str(le.id), name="C2", parent_id=str(root.id))).value
        gc = (await use_case.create(TENANT, str(le.id), name="GC", parent_id=str(c1.id))).value

        children = await use_case.list_children(TENANT, str(root.id))
        child_ids = {u.id for u in children}
        assert c1.id in child_ids
        assert c2.id in child_ids
        assert gc.id not in child_ids

    async def test_list_root_units(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        root1 = (await use_case.create(TENANT, str(le.id), name="R1")).value
        root2 = (await use_case.create(TENANT, str(le.id), name="R2")).value
        child = (await use_case.create(TENANT, str(le.id), name="C", parent_id=str(root1.id))).value

        roots = await use_case.list_root_units(TENANT, str(le.id))
        root_ids = {u.id for u in roots}
        assert root1.id in root_ids
        assert root2.id in root_ids
        assert child.id not in root_ids

    async def test_update_archived_unit_blocked(
        self, use_case: OrgUnitUseCase, repos: tuple
    ) -> None:
        le_repo, _ = repos
        le = await le_repo.save(LegalEntity.create(TENANT, name="LE"))
        unit = (await use_case.create(TENANT, str(le.id), name="Unit")).value
        # No children, can archive
        await use_case.archive(TENANT, str(unit.id))
        result = await use_case.update(TENANT, str(unit.id), name="NewName")
        assert is_error(result)
        assert result.error.code.value == "conflict"
