"""Тесты домена вакансий и use case создания вакансии со stub-AI."""

from __future__ import annotations

import pytest

from ats.infra.container import build_container
from ats.modules.recruitment.application.create_vacancy import (
    CreateVacancyInput,
    CreateVacancyUseCase,
)
from ats.modules.recruitment.domain.vacancy import (
    RoleDescription,
    Seniority,
    Vacancy,
    VacancyStatus,
)
from ats.shared.ids import IdempotencyKey, ProvenanceId, TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


class TestVacancyAggregate:
    def test_create_publishes_event(self) -> None:
        role = RoleDescription(
            title="Dev",
            seniority=Seniority.MIDDLE,
            team="Backend",
            description="desc",
        )
        vacancy = Vacancy.create(tenant_id=TENANT, role=role)
        events = vacancy.collect_events()

        assert vacancy.status == VacancyStatus.DRAFT
        assert len(events) == 1
        assert events[0].__class__.__name__ == "VacancyCreated"

    def test_activate_requires_description(self) -> None:
        role = RoleDescription(
            title="Dev", seniority=Seniority.JUNIOR, team="X", description=""
        )
        vacancy = Vacancy.create(tenant_id=TENANT, role=role)
        with pytest.raises(ValueError, match="role description"):
            vacancy.activate()

    def test_attach_screening_criteria_publishes_event(self) -> None:
        role = RoleDescription(
            title="Dev", seniority=Seniority.MIDDLE, team="X", description="d"
        )
        vacancy = Vacancy.create(tenant_id=TENANT, role=role)
        vacancy.collect_events()  # clean

        vacancy.attach_screening_criteria(ProvenanceId.generate())
        events = vacancy.collect_events()

        assert vacancy.screening_criteria_provenance is not None
        assert len(events) == 1
        assert events[0].__class__.__name__ == "ScreeningCriteriaGenerated"


class TestCreateVacancyUseCase:
    @pytest.mark.asyncio
    async def test_creates_with_criteria(self) -> None:
        use_case = build_container().create_vacancy
        dto = CreateVacancyInput(
            title="Middle Python Developer",
            seniority=Seniority.MIDDLE,
            team="Backend",
            description="Backend на FastAPI. Нужно: Python, REST API, async.",
            requirements=["Python", "FastAPI"],
        )
        result = await use_case.execute(TENANT, dto, IdempotencyKey("k1"))

        assert not is_error(result)
        res = result.value
        assert res.vacancy_id is not None
        assert res.criteria is not None
        assert res.criteria_provenance_id is not None
        assert res.criteria_error is None
        assert len(res.criteria.groups) == 4  # stub возвращает 4 группы

    @pytest.mark.asyncio
    async def test_rejects_empty_description(self) -> None:
        use_case = build_container().create_vacancy
        dto = CreateVacancyInput(
            title="Dev",
            seniority=Seniority.JUNIOR,
            team="X",
            description="",
        )
        result = await use_case.execute(TENANT, dto, IdempotencyKey("k2"))

        assert is_error(result)
        assert result.error.code.value == "validation"

    @pytest.mark.asyncio
    async def test_rejects_empty_title(self) -> None:
        use_case = build_container().create_vacancy
        dto = CreateVacancyInput(
            title="",
            seniority=Seniority.JUNIOR,
            team="X",
            description="valid desc",
        )
        result = await use_case.execute(TENANT, dto, IdempotencyKey("k3"))

        assert is_error(result)
        assert result.error.code.value == "validation"
