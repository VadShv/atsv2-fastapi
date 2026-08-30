"""Tests for JUGO-202: Visibility scopes (department-based)."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from ats.infra.stubs_org import InMemoryLegalEntityRepository, InMemoryOrgUnitRepository
from ats.modules.identity.domain.rbac import (
    Permission,
    Role,
    User,
    VisibilityScope,
)
from ats.modules.organization.application.visibility import (
    VisibilityFilter,
    can_see_org_unit,
    resolve_visibility,
)
from ats.modules.organization.domain import LegalEntity, OrgUnit
from ats.shared.ids import TenantId

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def _make_user(scope: VisibilityScope, permissions: frozenset[Permission] | None = None) -> User:
    role = Role(
        id=uuid4(),
        tenant_id=TENANT.value,
        name="test_role",
        permissions=permissions or frozenset(),
        scope=scope,
        is_system=False,
    )
    return User(
        id=uuid4(),
        tenant_id=TENANT.value,
        email="test@ats.local",
        role=role,
    )


@pytest_asyncio.fixture
async def org_setup() -> tuple:
    """Create a 3-level tree: Root -> Child -> Grandchild."""
    le_repo = InMemoryLegalEntityRepository()
    org_repo = InMemoryOrgUnitRepository()

    le = LegalEntity.create(TENANT, name="LE")
    root = OrgUnit.create(TENANT, le.id, name="Root")
    child = OrgUnit.create(TENANT, le.id, name="Child", parent_id=root.id, parent_path=root.path)
    grandchild = OrgUnit.create(
        TENANT, le.id, name="GC", parent_id=child.id, parent_path=child.path
    )
    other = OrgUnit.create(TENANT, le.id, name="Other")

    await le_repo.save(le)
    for u in [root, child, grandchild, other]:
        await org_repo.save(u)

    return org_repo, root, child, grandchild, other


class TestVisibilityAll:
    async def test_all_scope_unrestricted(self, org_setup: tuple) -> None:
        org_repo, root, child, grandchild, other = org_setup
        user = _make_user(VisibilityScope.ALL)
        vf = await resolve_visibility(user, TENANT, org_repo, user_org_unit_id=root.id)
        assert vf.is_unrestricted is True
        assert can_see_org_unit(vf, root.id)
        assert can_see_org_unit(vf, other.id)
        assert can_see_org_unit(vf, None)


class TestVisibilityOwn:
    async def test_own_scope_empty(self, org_setup: tuple) -> None:
        org_repo, root, child, grandchild, other = org_setup
        user = _make_user(VisibilityScope.OWN)
        vf = await resolve_visibility(user, TENANT, org_repo)
        assert vf.scope == VisibilityScope.OWN
        assert vf.is_empty is True
        # Own scope: resources without org_unit are visible (filtered by owner separately)
        assert can_see_org_unit(vf, None)
        # Resources with org_unit: not visible in own scope
        assert not can_see_org_unit(vf, root.id)


class TestVisibilityDepartment:
    async def test_department_sees_subtree(self, org_setup: tuple) -> None:
        org_repo, root, child, grandchild, other = org_setup
        user = _make_user(VisibilityScope.DEPARTMENT)
        vf = await resolve_visibility(user, TENANT, org_repo, user_org_unit_id=child.id)
        assert vf.scope == VisibilityScope.DEPARTMENT
        assert not vf.is_unrestricted
        # Sees child + grandchild (subtree of child)
        assert can_see_org_unit(vf, child.id)
        assert can_see_org_unit(vf, grandchild.id)
        # Does not see root (parent) or other
        assert not can_see_org_unit(vf, root.id)
        assert not can_see_org_unit(vf, other.id)

    async def test_department_root_sees_everything(self, org_setup: tuple) -> None:
        org_repo, root, child, grandchild, other = org_setup
        user = _make_user(VisibilityScope.DEPARTMENT)
        vf = await resolve_visibility(user, TENANT, org_repo, user_org_unit_id=root.id)
        # Root's subtree includes everything except 'other'
        assert can_see_org_unit(vf, root.id)
        assert can_see_org_unit(vf, child.id)
        assert can_see_org_unit(vf, grandchild.id)
        assert not can_see_org_unit(vf, other.id)

    async def test_department_no_org_unit_assignment(self, org_setup: tuple) -> None:
        org_repo, root, child, grandchild, other = org_setup
        user = _make_user(VisibilityScope.DEPARTMENT)
        vf = await resolve_visibility(user, TENANT, org_repo, user_org_unit_id=None)
        assert vf.is_empty is True
        assert not can_see_org_unit(vf, root.id)
        assert not can_see_org_unit(vf, child.id)

    async def test_department_archived_included_in_subtree(
        self, org_setup: tuple
    ) -> None:
        org_repo, root, child, grandchild, other = org_setup
        # Archive grandchild
        grandchild.archive()
        await org_repo.save(grandchild)

        user = _make_user(VisibilityScope.DEPARTMENT)
        vf = await resolve_visibility(user, TENANT, org_repo, user_org_unit_id=root.id)
        # Archived units still appear in subtree for visibility resolution
        assert can_see_org_unit(vf, grandchild.id)


class TestCanSeeOrgUnit:
    def test_all_sees_none_org_unit(self) -> None:
        vf = VisibilityFilter(
            scope=VisibilityScope.ALL,
            org_unit_ids=None,
            user_id=uuid4(),
        )
        assert can_see_org_unit(vf, None)
        assert can_see_org_unit(vf, uuid4())

    def test_own_sees_none_org_unit(self) -> None:
        vf = VisibilityFilter(
            scope=VisibilityScope.OWN,
            org_unit_ids=frozenset(),
            user_id=uuid4(),
        )
        # None org_unit -> visible in OWN (owner check is separate)
        assert can_see_org_unit(vf, None)
        # Specific org_unit -> not visible
        assert not can_see_org_unit(vf, uuid4())

    def test_department_sees_only_subtree(self) -> None:
        unit_id = uuid4()
        vf = VisibilityFilter(
            scope=VisibilityScope.DEPARTMENT,
            org_unit_ids=frozenset({unit_id}),
            user_id=uuid4(),
        )
        assert can_see_org_unit(vf, unit_id)
        assert not can_see_org_unit(vf, uuid4())
        assert not can_see_org_unit(vf, None)
