"""Доменная модель RBAC (SECURE FIRST, ТЗ §3.1-3.2).

Роль → разрешения (resource:action) + скоупы видимости.
Deny-by-default: всё, что явно не разрешено, — запрещено.
Продуктовый код не содержит захардкоженных проверок ролей, только
require_permission("vacancy:update").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class VisibilityScope(StrEnum):
    """Скоуп видимости данных (ТЗ §3.1)."""

    OWN = "own"  # свои вакансии/кандидаты
    DEPARTMENT = "department"  # вакансии подразделения
    ALL = "all"  # все


@dataclass(frozen=True)
class Permission:
    """Разрешение в формате resource:action (напр. vacancy:create)."""

    value: str

    def __post_init__(self) -> None:
        if ":" not in self.value:
            raise ValueError(f"Permission must be 'resource:action', got {self.value!r}")

    @property
    def resource(self) -> str:
        return self.value.split(":")[0]

    @property
    def action(self) -> str:
        return self.value.split(":", 1)[1]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Role:
    """Роль: набор разрешений + скоуп видимости."""

    id: UUID
    tenant_id: UUID
    name: str
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    scope: VisibilityScope = VisibilityScope.OWN
    is_system: bool = False

    def has_permission(self, perm: str) -> bool:
        """Deny-by-default: True только если разрешение явно есть."""
        return Permission(perm) in self.permissions


@dataclass(frozen=True)
class User:
    """Пользователь системы с ролью."""

    id: UUID
    tenant_id: UUID
    email: str
    role: Role | None = None
    is_active: bool = True

    def has_permission(self, perm: str) -> bool:
        """Проверка разрешения через роль (deny-by-default)."""
        if not self.is_active or self.role is None:
            return False
        return self.role.has_permission(perm)


# ---------------------------------------------------------------------------
# Системные роли-пресеты (ТЗ §3.2, редактируемые)
# ---------------------------------------------------------------------------


def _perms(*items: str) -> frozenset[Permission]:
    return frozenset(Permission(p) for p in items)


# Полный набор разрешений для администратора
ADMIN_PERMISSIONS = _perms(
    "*:*",  # wildcard — полный доступ
)

RECRUITER_PERMISSIONS = _perms(
    "vacancy:create",
    "vacancy:read",
    "vacancy:update",
    "vacancy:delete",
    "application:read",
    "application:update",
    "application:create",
    "candidate:read",
    "candidate:create",
    "candidate:update",
    "screening:run",
    "search:run",
    "scheduler:manage",
)

SOURCER_PERMISSIONS = _perms(
    "vacancy:read",
    "candidate:read",
    "candidate:create",
    "application:create",
    "search:run",
    "searchmap:read",
)

HIRING_MANAGER_PERMISSIONS = _perms(
    "application:read",
    "application:decide",
    "vacancy:read",
    "candidate:read",
)

VIEWER_PERMISSIONS = _perms(
    "vacancy:read",
    "candidate:read",
    "application:read",
    "audit:read",
)

API_CLIENT_PERMISSIONS = _perms(
    "candidate:read",
    "application:read",
    "application:write",
    "webhook:manage",
)


# Карта: имя системной роли → (разрешения, скоуп)
SYSTEM_ROLE_PRESETS: dict[str, tuple[frozenset[Permission], VisibilityScope]] = {
    "admin": (ADMIN_PERMISSIONS, VisibilityScope.ALL),
    "head_of_recruiting": (
        _perms(
            "vacancy:read",
            "vacancy:update",
            "application:read",
            "application:update",
            "candidate:read",
            "analytics:read",
            "pipeline:manage",
        ),
        VisibilityScope.ALL,
    ),
    "recruiter": (RECRUITER_PERMISSIONS, VisibilityScope.OWN),
    "sourcer": (SOURCER_PERMISSIONS, VisibilityScope.ALL),
    "hiring_manager": (HIRING_MANAGER_PERMISSIONS, VisibilityScope.OWN),
    "viewer": (VIEWER_PERMISSIONS, VisibilityScope.ALL),
    "api_client": (API_CLIENT_PERMISSIONS, VisibilityScope.ALL),
}


def permissions_for_role(role_name: str) -> frozenset[Permission]:
    """Получить разрешения системной роли-пресета."""
    preset = SYSTEM_ROLE_PRESETS.get(role_name)
    if preset is None:
        return frozenset()
    return preset[0]


def scope_for_role(role_name: str) -> VisibilityScope:
    """Получить скоуп видимости системной роли."""
    preset = SYSTEM_ROLE_PRESETS.get(role_name)
    if preset is None:
        return VisibilityScope.OWN
    return preset[1]
