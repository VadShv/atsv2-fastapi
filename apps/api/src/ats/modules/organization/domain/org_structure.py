"""Домен оргструктуры (JUGO-200, ТЗ §5.1).

Модель: Tenant → LegalEntity → OrgUnit (дерево, ltree).
Защита от циклов, архивирование вместо удаления.

LegalEntity — юридическое лицо (ООО «Ромашка», Inc. и т.д.).
OrgUnit — подразделение в дереве (департамент, команда, отдел).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import TenantId


class LegalEntityType(StrEnum):
    """Тип юридического лица."""

    OOO = "ooo"
    OAO = "oao"
    ZAO = "zao"
    IP = "ip"
    INC = "inc"
    LLC = "llc"
    OTHER = "other"


# --- Доменные события ---


@dataclass(frozen=True)
class LegalEntityCreated(DomainEvent):
    legal_entity_id: UUID = field(default_factory=uuid4)
    name: str = ""


@dataclass(frozen=True)
class LegalEntityUpdated(DomainEvent):
    legal_entity_id: UUID = field(default_factory=uuid4)
    name: str = ""


@dataclass(frozen=True)
class LegalEntityArchived(DomainEvent):
    legal_entity_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class OrgUnitCreated(DomainEvent):
    org_unit_id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    name: str = ""
    path: str = ""


@dataclass(frozen=True)
class OrgUnitUpdated(DomainEvent):
    org_unit_id: UUID = field(default_factory=uuid4)
    name: str = ""


@dataclass(frozen=True)
class OrgUnitArchived(DomainEvent):
    org_unit_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class OrgUnitMoved(DomainEvent):
    org_unit_id: UUID = field(default_factory=uuid4)
    old_parent_id: UUID | None = None
    new_parent_id: UUID | None = None
    new_path: str = ""


# --- Агрегаты ---


@dataclass
class LegalEntity(AggregateRoot):
    """Юридическое лицо (ТЗ §5.1: Tenant → LegalEntity).

    Инварианты:
    - Имя непустое и уникально в рамках тенанта.
    - Архивирование вместо удаления: archived=True блокирует использование.
    """

    id: UUID
    tenant_id: TenantId
    name: str
    type: LegalEntityType = LegalEntityType.OTHER
    inn: str = ""
    full_name: str = ""
    is_archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        name: str,
        type: LegalEntityType = LegalEntityType.OTHER,
        inn: str = "",
        full_name: str = "",
    ) -> LegalEntity:
        if not name or not name.strip():
            raise ValueError("Имя юридического лица не может быть пустым")
        entity = cls(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name.strip(),
            type=type,
            inn=inn.strip(),
            full_name=full_name.strip() or name.strip(),
        )
        entity._record(
            LegalEntityCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={"name": entity.name, "type": entity.type.value},
                legal_entity_id=entity.id,
                name=entity.name,
            )
        )
        return entity

    def update(
        self,
        name: str | None = None,
        type: LegalEntityType | None = None,
        inn: str | None = None,
        full_name: str | None = None,
    ) -> None:
        changed = False
        if name is not None:
            if not name.strip():
                raise ValueError("Имя юридического лица не может быть пустым")
            self.name = name.strip()
            changed = True
        if type is not None:
            self.type = type
            changed = True
        if inn is not None:
            self.inn = inn.strip()
            changed = True
        if full_name is not None:
            self.full_name = full_name.strip()
            changed = True
        if changed:
            self.updated_at = datetime.now(UTC)
            self._record(
                LegalEntityUpdated(
                    event_id=uuid4(),
                    occurred_at=datetime.now(UTC),
                    tenant_id=self.tenant_id.value,
                    payload={"name": self.name},
                    legal_entity_id=self.id,
                    name=self.name,
                )
            )

    def archive(self) -> None:
        if self.is_archived:
            return
        self.is_archived = True
        self.updated_at = datetime.now(UTC)
        self._record(
            LegalEntityArchived(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={},
                legal_entity_id=self.id,
            )
        )


class CycleDetectedError(Exception):
    """Попытка создать цикл в дереве OrgUnit."""


@dataclass
class OrgUnit(AggregateRoot):
    """Подразделение в дереве (ТЗ §5.1: LegalEntity → OrgUnit, ltree).

    Инварианты:
    - path формирует ltree-путь: root узел = "<id>", потомок = "<parent_path>.<id>".
    - parent_id должен указывать на узел того же legal_entity (если задан).
    - Архивирование вместо удаления: архивный узел не может быть parent.
    - Защита от циклов: узел нельзя переместить под собственного потомка.
    """

    id: UUID
    tenant_id: TenantId
    legal_entity_id: UUID
    name: str
    parent_id: UUID | None = None
    path: str = ""  # ltree-путь, напр. "uuid1.uuid2.uuid3"
    is_archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        legal_entity_id: UUID,
        name: str,
        parent_id: UUID | None = None,
        parent_path: str = "",
    ) -> OrgUnit:
        if not name or not name.strip():
            raise ValueError("Имя подразделения не может быть пустым")
        unit_id = uuid4()
        # ltree использует только латиницу, цифры и подчёркивание.
        # UUID с дефисами нужно нормализовать: заменяем '-' на '_'.
        path_segment = str(unit_id).replace("-", "_")
        if parent_id is not None:
            if not parent_path:
                raise ValueError("parent_path обязателен, когда parent_id задан")
            path = f"{parent_path}.{path_segment}"
        else:
            path = path_segment
        unit = cls(
            id=unit_id,
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            name=name.strip(),
            parent_id=parent_id,
            path=path,
        )
        unit._record(
            OrgUnitCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={"name": unit.name, "path": unit.path},
                org_unit_id=unit.id,
                legal_entity_id=legal_entity_id,
                parent_id=parent_id,
                name=unit.name,
                path=unit.path,
            )
        )
        return unit

    def update(self, name: str | None = None) -> None:
        if name is not None:
            if not name.strip():
                raise ValueError("Имя подразделения не может быть пустым")
            self.name = name.strip()
            self.updated_at = datetime.now(UTC)
            self._record(
                OrgUnitUpdated(
                    event_id=uuid4(),
                    occurred_at=datetime.now(UTC),
                    tenant_id=self.tenant_id.value,
                    payload={"name": self.name},
                    org_unit_id=self.id,
                    name=self.name,
                )
            )

    def archive(self) -> None:
        if self.is_archived:
            return
        self.is_archived = True
        self.updated_at = datetime.now(UTC)
        self._record(
            OrgUnitArchived(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={},
                org_unit_id=self.id,
            )
        )

    def move(
        self,
        new_parent_id: UUID | None,
        new_parent_path: str,
        descendant_paths: set[str] | None = None,
    ) -> str:
        """Переместить узел под нового родителя.

        Возвращает новый path узла.
        Проверяет защиту от циклов: нельзя переместить узел под своего потомка.

        Args:
            new_parent_id: ID нового родителя (None = корень).
            new_parent_path: path нового родителя ("" если корень).
            descendant_paths: множество path всех потомков текущего узла
                              (для проверки циклов).
        """
        old_parent_id = self.parent_id

        path_segment = str(self.id).replace("-", "_")
        if new_parent_id is not None:
            if not new_parent_path:
                raise ValueError("new_parent_path обязателен, когда new_parent_id задан")
            new_path = f"{new_parent_path}.{path_segment}"

            # Защита от циклов: новый родитель не должен быть потомком текущего узла.
            if descendant_paths is not None:
                # Проверяем, что new_parent_path начинается с нашего текущего path
                # (т.е. новый родитель — наш потомок).
                if new_parent_path == self.path or new_parent_path.startswith(self.path + "."):
                    raise CycleDetectedError(
                        f"Нельзя переместить узел {self.id} под его собственного потомка"
                    )
                # Также проверяем через множество path потомков.
                if new_parent_path in descendant_paths:
                    raise CycleDetectedError(
                        f"Нельзя переместить узел {self.id} под его собственного потомка"
                    )

            # Нельзя переместить под архивный узел.
            # (Эта проверка выполняется в use case, т.к. требует доступа к репозиторию.)
        else:
            new_path = path_segment

        self.parent_id = new_parent_id
        self.path = new_path
        self.updated_at = datetime.now(UTC)
        self._record(
            OrgUnitMoved(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={
                    "old_parent_id": str(old_parent_id) if old_parent_id else None,
                    "new_parent_id": str(new_parent_id) if new_parent_id else None,
                    "new_path": new_path,
                },
                org_unit_id=self.id,
                old_parent_id=old_parent_id,
                new_parent_id=new_parent_id,
                new_path=new_path,
            )
        )
        return new_path
