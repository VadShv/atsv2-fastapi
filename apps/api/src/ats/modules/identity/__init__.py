"""Модуль identity: аутентификация и модель доступа (RBAC).

SECURE FIRST (ТЗ §3.1-3.2, §15):
- RBAC: role → permissions (resource:action) + скоупы видимости.
- Deny-by-default: всё, что явно не разрешено, — запрещено.
- Сессии HttpOnly+Secure+SameSite, CSRF-токены, 2FA для админов.
- Системные роли-пресеты (редактируемые).
"""

from ats.modules.identity.domain.rbac import (
    Permission,
    Role,
    User,
    VisibilityScope,
)
from ats.modules.identity.domain.session import Session

__all__ = ["Permission", "Role", "Session", "User", "VisibilityScope"]
