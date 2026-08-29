"""Postgres-реализация репозитория вакансий (RLS через tenant_session)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ats.infra.db.mappers import orm_to_vacancy, vacancy_to_orm
from ats.infra.db.models.recruitment import VacancyORM
from ats.infra.db.session import tenant_session
from ats.modules.recruitment.domain.vacancy import Vacancy
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.shared.ids import TenantId, VacancyId


class PgVacancyRepository(VacancyRepository):
    """Postgres-репозиторий. Идемпотентный upsert по id. RLS изолирует тенанты."""

    async def save(self, vacancy: Vacancy) -> VacancyId:
        orm = vacancy_to_orm(vacancy)
        async with tenant_session(vacancy.tenant_id.value) as session:
            # Upsert: вставить или обновить по id
            stmt = pg_insert(VacancyORM).values(
                id=orm.id,
                tenant_id=orm.tenant_id,
                title=orm.title,
                seniority=orm.seniority,
                team=orm.team,
                status=orm.status,
                role_description=orm.role_description,
                requirements=orm.requirements,
                nice_to_have=orm.nice_to_have,
                screening_criteria_provenance=orm.screening_criteria_provenance,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[VacancyORM.id],
                set_={
                    "title": stmt.excluded.title,
                    "status": stmt.excluded.status,
                    "role_description": stmt.excluded.role_description,
                    "requirements": stmt.excluded.requirements,
                    "nice_to_have": stmt.excluded.nice_to_have,
                    "screening_criteria_provenance": stmt.excluded.screening_criteria_provenance,
                },
            )
            await session.execute(stmt)
            await session.commit()
        return vacancy.id

    async def get(
        self, tenant_id: TenantId, vacancy_id: VacancyId
    ) -> Vacancy | None:
        async with tenant_session(tenant_id.value) as session:
            stmt = select(VacancyORM).where(VacancyORM.id == vacancy_id.value)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return orm_to_vacancy(row)

    async def list_by_tenant(
        self, tenant_id: TenantId, limit: int = 50, offset: int = 0
    ) -> list[Vacancy]:
        async with tenant_session(tenant_id.value) as session:
            stmt = (
                select(VacancyORM)
                .order_by(VacancyORM.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [orm_to_vacancy(row) for row in result.scalars().all()]
