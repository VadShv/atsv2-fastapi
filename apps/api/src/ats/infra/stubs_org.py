"""In-memory репозитории оргструктуры (JUGO-200, dev-режим)."""

from __future__ import annotations

from uuid import UUID

from ats.modules.organization.domain import LegalEntity, OrgUnit
from ats.modules.organization.ports import LegalEntityRepository, OrgUnitRepository
from ats.shared.ids import TenantId


class InMemoryLegalEntityRepository(LegalEntityRepository):
    """In-memory хранилище юридических лиц."""

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, UUID], LegalEntity] = {}

    async def get_by_id(self, tenant_id: TenantId, legal_entity_id: str) -> LegalEntity | None:
        return self._store.get((tenant_id.value, UUID(legal_entity_id)))

    async def list_all(
        self, tenant_id: TenantId, include_archived: bool = False
    ) -> list[LegalEntity]:
        return [
            e
            for (tid, _), e in self._store.items()
            if tid == tenant_id.value and (include_archived or not e.is_archived)
        ]

    async def find_by_name(self, tenant_id: TenantId, name: str) -> LegalEntity | None:
        for e in self._store.values():
            if e.tenant_id == tenant_id and e.name.lower() == name.strip().lower():
                return e
        return None

    async def save(self, entity: LegalEntity) -> LegalEntity:
        self._store[(entity.tenant_id.value, entity.id)] = entity
        return entity

    async def delete(self, tenant_id: TenantId, legal_entity_id: str) -> None:
        self._store.pop((tenant_id.value, UUID(legal_entity_id)), None)


class InMemoryOrgUnitRepository(OrgUnitRepository):
    """In-memory хранилище подразделений (дерево через path)."""

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, UUID], OrgUnit] = {}

    async def get_by_id(self, tenant_id: TenantId, org_unit_id: str) -> OrgUnit | None:
        return self._store.get((tenant_id.value, UUID(org_unit_id)))

    async def list_by_legal_entity(
        self,
        tenant_id: TenantId,
        legal_entity_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        le_id = UUID(legal_entity_id)
        return [
            u
            for u in self._store.values()
            if u.tenant_id == tenant_id
            and u.legal_entity_id == le_id
            and (include_archived or not u.is_archived)
        ]

    async def list_children(
        self,
        tenant_id: TenantId,
        parent_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        pid = UUID(parent_id)
        return [
            u
            for u in self._store.values()
            if u.tenant_id == tenant_id
            and u.parent_id == pid
            and (include_archived or not u.is_archived)
        ]

    async def list_root_units(
        self,
        tenant_id: TenantId,
        legal_entity_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        le_id = UUID(legal_entity_id)
        return [
            u
            for u in self._store.values()
            if u.tenant_id == tenant_id
            and u.legal_entity_id == le_id
            and u.parent_id is None
            and (include_archived or not u.is_archived)
        ]

    async def list_descendants(self, tenant_id: TenantId, org_unit_id: str) -> list[OrgUnit]:
        """Потомки — все узлы, чей path начинается с path текущего + '.'."""
        unit = await self.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return []
        prefix = unit.path + "."
        return [
            u
            for u in self._store.values()
            if u.tenant_id == tenant_id and u.path.startswith(prefix)
        ]

    async def get_subtree(
        self,
        tenant_id: TenantId,
        org_unit_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        """Узел + все потомки."""
        unit = await self.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return []
        prefix = unit.path + "."
        result: list[OrgUnit] = []
        if include_archived or not unit.is_archived:
            result.append(unit)
        for u in self._store.values():
            if (
                u.tenant_id == tenant_id
                and u.path.startswith(prefix)
                and (include_archived or not u.is_archived)
            ):
                result.append(u)
        return result

    async def save(self, unit: OrgUnit) -> OrgUnit:
        self._store[(unit.tenant_id.value, unit.id)] = unit
        return unit

    async def delete(self, tenant_id: TenantId, org_unit_id: str) -> None:
        self._store.pop((tenant_id.value, UUID(org_unit_id)), None)

    async def count_children(
        self, tenant_id: TenantId, parent_id: str, include_archived: bool = False
    ) -> int:
        children = await self.list_children(tenant_id, parent_id, include_archived)
        return len(children)
