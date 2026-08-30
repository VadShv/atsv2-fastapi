"""Порты модуля оргструктуры."""

from ats.modules.organization.ports.org_repository import (
    LegalEntityRepository,
    OrgUnitRepository,
)

__all__ = ["LegalEntityRepository", "OrgUnitRepository"]
