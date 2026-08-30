"""Порты репозиториев оргструктуры (JUGO-200)."""

from __future__ import annotations

from typing import Protocol

from ats.modules.organization.domain import LegalEntity, OrgUnit
from ats.shared.ids import TenantId


class LegalEntityRepository(Protocol):
    """Репозиторий юридических лиц."""

    async def get_by_id(self, tenant_id: TenantId, legal_entity_id: str) -> LegalEntity | None: ...

    async def list_all(
        self, tenant_id: TenantId, include_archived: bool = False
    ) -> list[LegalEntity]: ...

    async def find_by_name(self, tenant_id: TenantId, name: str) -> LegalEntity | None: ...

    async def save(self, entity: LegalEntity) -> LegalEntity: ...

    async def delete(self, tenant_id: TenantId, legal_entity_id: str) -> None: ...


class OrgUnitRepository(Protocol):
    """Репозиторий подразделений (дерево)."""

    async def get_by_id(self, tenant_id: TenantId, org_unit_id: str) -> OrgUnit | None: ...

    async def list_by_legal_entity(
        self, tenant_id: TenantId, legal_entity_id: str, include_archived: bool = False
    ) -> list[OrgUnit]: ...

    async def list_children(
        self, tenant_id: TenantId, parent_id: str, include_archived: bool = False
    ) -> list[OrgUnit]: ...

    async def list_root_units(
        self, tenant_id: TenantId, legal_entity_id: str, include_archived: bool = False
    ) -> list[OrgUnit]: ...

    async def list_descendants(self, tenant_id: TenantId, org_unit_id: str) -> list[OrgUnit]:
        """Все потомки узла (по ltree path)."""
        ...

    async def get_subtree(
        self, tenant_id: TenantId, org_unit_id: str, include_archived: bool = False
    ) -> list[OrgUnit]:
        """Узел + все его потомки."""
        ...

    async def save(self, unit: OrgUnit) -> OrgUnit: ...

    async def delete(self, tenant_id: TenantId, org_unit_id: str) -> None: ...

    async def count_children(
        self, tenant_id: TenantId, parent_id: str, include_archived: bool = False
    ) -> int: ...
