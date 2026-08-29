"""Маппинг между доменными объектами и ORM.

Изоляция: домен не знает про ORM. Этот слой переводит агрегат <-> строку таблицы.
"""

from __future__ import annotations

from uuid import UUID

from ats.infra.db.models.recruitment import VacancyORM
from ats.modules.recruitment.domain.vacancy import (
    RoleDescription,
    Seniority,
    Vacancy,
    VacancyStatus,
)
from ats.shared.ids import ProvenanceId, TenantId, VacancyId


def vacancy_to_orm(vacancy: Vacancy) -> VacancyORM:
    return VacancyORM(
        id=vacancy.id.value,
        tenant_id=vacancy.tenant_id.value,
        title=vacancy.role.title,
        seniority=vacancy.role.seniority.value,
        team=vacancy.role.team,
        status=vacancy.status.value,
        role_description=vacancy.role.description,
        requirements=vacancy.role.requirements,
        nice_to_have=vacancy.role.nice_to_have,
        screening_criteria_provenance=(
            vacancy.screening_criteria_provenance.value
            if vacancy.screening_criteria_provenance
            else None
        ),
    )


def orm_to_vacancy(row: VacancyORM) -> Vacancy:
    role = RoleDescription(
        title=row.title,
        seniority=Seniority(row.seniority),
        team=row.team,
        description=row.role_description,
        requirements=list(row.requirements or []),
        nice_to_have=list(row.nice_to_have or []),
    )
    vacancy = Vacancy(
        id=VacancyId(row.id),
        tenant_id=TenantId(row.tenant_id),
        role=role,
        status=VacancyStatus(row.status),
        screening_criteria_provenance=(
            ProvenanceId(row.screening_criteria_provenance)
            if row.screening_criteria_provenance
            else None
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    return vacancy
