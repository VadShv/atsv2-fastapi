"""Скоупы видимости по подразделениям (JUGO-202).

Интеграция с permission-чекером (JUGO-022): фильтрация ресурсов
по скоупу видимости пользователя.

ТЗ §3.1: скоупы видимости (свои вакансии / вакансии подразделения / все).

VisibilityFilter определяет, какие org_unit_ids видит пользователь:
- OWN: только свои ресурсы (по user_id, без фильтра по подразделениям)
- DEPARTMENT: ресурсы своего подразделения + всех потомков
- ALL: все ресурсы (без фильтра)
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ats.modules.identity.domain.rbac import User, VisibilityScope
from ats.modules.organization.ports import OrgUnitRepository
from ats.shared.ids import TenantId


@dataclass(frozen=True)
class VisibilityFilter:
    """Результат разрешения скоупа видимости.

    Attributes:
        scope: Тип скоупа (OWN / DEPARTMENT / ALL).
        org_unit_ids: Множество ID подразделений, которые видит пользователь.
                      None = без фильтра (ALL). Пустое множество = ничего (OWN без привязки).
        user_id: ID пользователя (для OWN-фильтрации по владельцу).
    """

    scope: VisibilityScope
    org_unit_ids: frozenset[UUID] | None
    user_id: UUID | None

    @property
    def is_unrestricted(self) -> bool:
        """True = пользователь видит всё (ALL)."""
        return self.org_unit_ids is None

    @property
    def is_empty(self) -> bool:
        """True = пользователь не видит ничего по подразделениям."""
        return self.org_unit_ids is not None and len(self.org_unit_ids) == 0


async def resolve_visibility(
    user: User,
    tenant_id: TenantId,
    org_unit_repo: OrgUnitRepository,
    user_org_unit_id: UUID | None = None,
) -> VisibilityFilter:
    """Разрешить скоуп видимости для пользователя.

    Args:
        user: Текущий пользователь с ролью и скоупом.
        tenant_id: ID тенанта.
        org_unit_repo: Репозиторий подразделений (для получения поддерева).
        user_org_unit_id: ID подразделения пользователя (если DEPARTMENT scope).

    Returns:
        VisibilityFilter с org_unit_ids или None (ALL).
    """
    scope = user.role.scope if user.role else VisibilityScope.OWN

    if scope == VisibilityScope.ALL:
        return VisibilityFilter(
            scope=VisibilityScope.ALL,
            org_unit_ids=None,
            user_id=user.id,
        )

    if scope == VisibilityScope.OWN:
        return VisibilityFilter(
            scope=VisibilityScope.OWN,
            org_unit_ids=frozenset(),
            user_id=user.id,
        )

    # DEPARTMENT: пользователь видит своё подразделение + всех потомков.
    if user_org_unit_id is None:
        # Нет привязки к подразделению — ничего не видно по департаменту.
        return VisibilityFilter(
            scope=VisibilityScope.DEPARTMENT,
            org_unit_ids=frozenset(),
            user_id=user.id,
        )

    subtree = await org_unit_repo.get_subtree(
        tenant_id, str(user_org_unit_id), include_archived=True
    )
    org_unit_ids = frozenset(u.id for u in subtree)
    return VisibilityFilter(
        scope=VisibilityScope.DEPARTMENT,
        org_unit_ids=org_unit_ids,
        user_id=user.id,
    )


def can_see_org_unit(
    filter: VisibilityFilter,
    org_unit_id: UUID | None,
) -> bool:
    """Проверить, видит ли пользователь ресурс в данном подразделении.

    Args:
        filter: Разрешённый скоуп видимости.
        org_unit_id: ID подразделения ресурса (None = не привязан).

    Returns:
        True если ресурс видим.
    """
    if filter.is_unrestricted:
        return True

    if org_unit_id is None:
        # Ресурс без привязки к подразделению:
        # - OWN: виден только если владелец = пользователь (проверяется отдельно)
        # - DEPARTMENT: не виден (нет привязки к подразделению)
        return filter.scope == VisibilityScope.OWN

    if filter.org_unit_ids is None:
        return True

    return org_unit_id in filter.org_unit_ids
