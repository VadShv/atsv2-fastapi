"""Use cases оргструктуры (JUGO-200).

CRUD для LegalEntity и OrgUnit + операции с деревом (move, subtree).
Архивирование вместо удаления. Защита от циклов при перемещении.
"""

from __future__ import annotations

from uuid import UUID

from ats.modules.organization.domain import (
    CycleDetectedError,
    LegalEntity,
    LegalEntityType,
    OrgUnit,
)
from ats.modules.organization.ports import LegalEntityRepository, OrgUnitRepository
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result


class LegalEntityUseCase:
    """Use case для юридических лиц."""

    def __init__(self, repo: LegalEntityRepository) -> None:
        self._repo = repo

    async def create(
        self,
        tenant_id: TenantId,
        name: str,
        type: LegalEntityType = LegalEntityType.OTHER,
        inn: str = "",
        full_name: str = "",
    ) -> Result[LegalEntity]:
        existing = await self._repo.find_by_name(tenant_id, name)
        if existing is not None:
            return Result.err(
                ErrorCode.CONFLICT,
                f"Юридическое лицо с именем «{name}» уже существует",
            )
        try:
            entity = LegalEntity.create(
                tenant_id=tenant_id,
                name=name,
                type=type,
                inn=inn,
                full_name=full_name,
            )
        except ValueError as e:
            return Result.err(ErrorCode.VALIDATION, str(e))
        await self._repo.save(entity)
        return Result.ok(entity)

    async def get(self, tenant_id: TenantId, legal_entity_id: str) -> Result[LegalEntity]:
        entity = await self._repo.get_by_id(tenant_id, legal_entity_id)
        if entity is None:
            return Result.err(ErrorCode.NOT_FOUND, "Юридическое лицо не найдено")
        return Result.ok(entity)

    async def list_all(
        self, tenant_id: TenantId, include_archived: bool = False
    ) -> list[LegalEntity]:
        return await self._repo.list_all(tenant_id, include_archived)

    async def update(
        self,
        tenant_id: TenantId,
        legal_entity_id: str,
        name: str | None = None,
        type: LegalEntityType | None = None,
        inn: str | None = None,
        full_name: str | None = None,
    ) -> Result[LegalEntity]:
        entity = await self._repo.get_by_id(tenant_id, legal_entity_id)
        if entity is None:
            return Result.err(ErrorCode.NOT_FOUND, "Юридическое лицо не найдено")
        if entity.is_archived:
            return Result.err(ErrorCode.CONFLICT, "Архивное юридическое лицо нельзя редактировать")
        # Проверка уникальности имени при изменении.
        if name is not None and name.strip().lower() != entity.name.lower():
            existing = await self._repo.find_by_name(tenant_id, name)
            if existing is not None and existing.id != entity.id:
                return Result.err(
                    ErrorCode.CONFLICT,
                    f"Юридическое лицо с именем «{name}» уже существует",
                )
        try:
            entity.update(name=name, type=type, inn=inn, full_name=full_name)
        except ValueError as e:
            return Result.err(ErrorCode.VALIDATION, str(e))
        await self._repo.save(entity)
        return Result.ok(entity)

    async def archive(self, tenant_id: TenantId, legal_entity_id: str) -> Result[None]:
        entity = await self._repo.get_by_id(tenant_id, legal_entity_id)
        if entity is None:
            return Result.err(ErrorCode.NOT_FOUND, "Юридическое лицо не найдено")
        entity.archive()
        await self._repo.save(entity)
        return Result.ok(None)


class OrgUnitUseCase:
    """Use case для подразделений (дерево)."""

    def __init__(
        self,
        org_repo: OrgUnitRepository,
        legal_entity_repo: LegalEntityRepository,
    ) -> None:
        self._org_repo = org_repo
        self._le_repo = legal_entity_repo

    async def create(
        self,
        tenant_id: TenantId,
        legal_entity_id: str,
        name: str,
        parent_id: str | None = None,
    ) -> Result[OrgUnit]:
        # Проверяем существование юридического лица.
        le = await self._le_repo.get_by_id(tenant_id, legal_entity_id)
        if le is None:
            return Result.err(ErrorCode.NOT_FOUND, "Юридическое лицо не найдено")
        if le.is_archived:
            return Result.err(
                ErrorCode.CONFLICT,
                "Нельзя создать подразделение в архивном юридическом лице",
            )

        parent_path = ""
        if parent_id is not None:
            parent = await self._org_repo.get_by_id(tenant_id, parent_id)
            if parent is None:
                return Result.err(ErrorCode.NOT_FOUND, "Родительское подразделение не найдено")
            if parent.legal_entity_id != le.id:
                return Result.err(
                    ErrorCode.VALIDATION,
                    "Родительское подразделение принадлежит другому юридическому лицу",
                )
            if parent.is_archived:
                return Result.err(
                    ErrorCode.CONFLICT,
                    "Нельзя создать подразделение под архивным узлом",
                )
            parent_path = parent.path

        try:
            unit = OrgUnit.create(
                tenant_id=tenant_id,
                legal_entity_id=le.id,
                name=name,
                parent_id=UUID(parent_id) if parent_id else None,
                parent_path=parent_path,
            )
        except ValueError as e:
            return Result.err(ErrorCode.VALIDATION, str(e))
        await self._org_repo.save(unit)
        return Result.ok(unit)

    async def get(self, tenant_id: TenantId, org_unit_id: str) -> Result[OrgUnit]:
        unit = await self._org_repo.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return Result.err(ErrorCode.NOT_FOUND, "Подразделение не найдено")
        return Result.ok(unit)

    async def list_by_legal_entity(
        self,
        tenant_id: TenantId,
        legal_entity_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        return await self._org_repo.list_by_legal_entity(
            tenant_id, legal_entity_id, include_archived
        )

    async def list_children(
        self,
        tenant_id: TenantId,
        parent_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        return await self._org_repo.list_children(tenant_id, parent_id, include_archived)

    async def list_root_units(
        self,
        tenant_id: TenantId,
        legal_entity_id: str,
        include_archived: bool = False,
    ) -> list[OrgUnit]:
        return await self._org_repo.list_root_units(tenant_id, legal_entity_id, include_archived)

    async def get_subtree(
        self,
        tenant_id: TenantId,
        org_unit_id: str,
        include_archived: bool = False,
    ) -> Result[list[OrgUnit]]:
        unit = await self._org_repo.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return Result.err(ErrorCode.NOT_FOUND, "Подразделение не найдено")
        subtree = await self._org_repo.get_subtree(tenant_id, org_unit_id, include_archived)
        return Result.ok(subtree)

    async def update(
        self,
        tenant_id: TenantId,
        org_unit_id: str,
        name: str | None = None,
    ) -> Result[OrgUnit]:
        unit = await self._org_repo.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return Result.err(ErrorCode.NOT_FOUND, "Подразделение не найдено")
        if unit.is_archived:
            return Result.err(ErrorCode.CONFLICT, "Архивное подразделение нельзя редактировать")
        try:
            unit.update(name=name)
        except ValueError as e:
            return Result.err(ErrorCode.VALIDATION, str(e))
        await self._org_repo.save(unit)
        return Result.ok(unit)

    async def archive(self, tenant_id: TenantId, org_unit_id: str) -> Result[None]:
        unit = await self._org_repo.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return Result.err(ErrorCode.NOT_FOUND, "Подразделение не найдено")
        # Проверяем, что нет активных детей.
        active_children = await self._org_repo.list_children(
            tenant_id, org_unit_id, include_archived=False
        )
        if active_children:
            return Result.err(
                ErrorCode.CONFLICT,
                "Нельзя архивировать подразделение с активными дочерними узлами. "
                "Сначала архивируйте дочерние.",
            )
        unit.archive()
        await self._org_repo.save(unit)
        return Result.ok(None)

    async def move(
        self,
        tenant_id: TenantId,
        org_unit_id: str,
        new_parent_id: str | None,
    ) -> Result[OrgUnit]:
        """Переместить узел под нового родителя с защитой от циклов."""
        unit = await self._org_repo.get_by_id(tenant_id, org_unit_id)
        if unit is None:
            return Result.err(ErrorCode.NOT_FOUND, "Подразделение не найдено")
        if unit.is_archived:
            return Result.err(ErrorCode.CONFLICT, "Архивное подразделение нельзя переместить")

        new_parent_path = ""
        if new_parent_id is not None:
            new_parent = await self._org_repo.get_by_id(tenant_id, new_parent_id)
            if new_parent is None:
                return Result.err(
                    ErrorCode.NOT_FOUND, "Новое родительское подразделение не найдено"
                )
            if new_parent.legal_entity_id != unit.legal_entity_id:
                return Result.err(
                    ErrorCode.VALIDATION,
                    "Нельзя переместить подразделение в другое юридическое лицо",
                )
            if new_parent.is_archived:
                return Result.err(
                    ErrorCode.CONFLICT,
                    "Нельзя переместить подразделение под архивный узел",
                )
            if new_parent.id == unit.id:
                return Result.err(
                    ErrorCode.VALIDATION,
                    "Нельзя переместить подразделение под самого себя",
                )
            new_parent_path = new_parent.path

        # Собираем пути всех потомков для проверки циклов.
        descendants = await self._org_repo.list_descendants(tenant_id, org_unit_id)
        descendant_paths = {d.path for d in descendants}

        try:
            old_path = unit.path
            new_path = unit.move(
                new_parent_id=UUID(new_parent_id) if new_parent_id else None,
                new_parent_path=new_parent_path,
                descendant_paths=descendant_paths,
            )
        except CycleDetectedError as e:
            return Result.err(ErrorCode.CONFLICT, str(e))

        # Обновляем пути всех потомков: заменяем старый префикс на новый.
        for desc in descendants:
            new_desc_path = new_path + desc.path[len(old_path) :]
            desc.path = new_desc_path
            await self._org_repo.save(desc)

        await self._org_repo.save(unit)
        return Result.ok(unit)
