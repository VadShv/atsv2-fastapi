"""Тесты БД-слоя: мапперы ORM↔домен (round-trip без реальной БД)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from ats.infra.db.mappers import orm_to_vacancy, vacancy_to_orm
from ats.modules.recruitment.domain.vacancy import (
    RoleDescription,
    Seniority,
    Vacancy,
    VacancyStatus,
)
from ats.shared.ids import ProvenanceId, TenantId


class TestVacancyMapper:
    def test_roundtrip_preserves_domain_state(self) -> None:
        tenant = TenantId.generate()
        role = RoleDescription(
            title="Middle Python Developer",
            seniority=Seniority.MIDDLE,
            team="Backend",
            description="desc",
            requirements=["Python", "FastAPI"],
            nice_to_have=["Docker"],
        )
        vacancy = Vacancy.create(tenant_id=tenant, role=role)
        vacancy.attach_screening_criteria(ProvenanceId.generate())
        vacancy.activate()

        # Домен → ORM
        orm = vacancy_to_orm(vacancy)
        assert orm.id == vacancy.id.value
        assert orm.tenant_id == tenant.value
        assert orm.title == "Middle Python Developer"
        assert orm.seniority == "middle"
        assert orm.status == "active"
        assert orm.requirements == ["Python", "FastAPI"]
        assert orm.screening_criteria_provenance is not None

        # ORM → Домен
        orm.created_at = datetime.now(timezone.utc)
        orm.updated_at = datetime.now(timezone.utc)
        restored = orm_to_vacancy(orm)
        assert restored.id == vacancy.id
        assert restored.role.title == vacancy.role.title
        assert restored.role.seniority == Seniority.MIDDLE
        assert restored.status == VacancyStatus.ACTIVE
        assert restored.screening_criteria_provenance is not None

    def test_roundtrip_without_criteria(self) -> None:
        tenant = TenantId.generate()
        role = RoleDescription(
            title="Junior", seniority=Seniority.JUNIOR, team="X", description="d"
        )
        vacancy = Vacancy.create(tenant_id=tenant, role=role)

        orm = vacancy_to_orm(vacancy)
        assert orm.screening_criteria_provenance is None
        orm.created_at = datetime.now(timezone.utc)
        orm.updated_at = datetime.now(timezone.utc)
        restored = orm_to_vacancy(orm)
        assert restored.screening_criteria_provenance is None
