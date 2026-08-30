"""Тесты E-12: вакансии — статусная машина, requirement sets, REST API.

JUGO-120: модель вакансии (статусы, команда найма, CRUD).
JUGO-121: версионируемые наборы критериев.
JUGO-122: REST + справочники.
JUGO-124: статусная машина (переходы, события, hired_count).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ats.infra.container_helpers import reset_container
from ats.infra.stubs_requirement_set_repository import (
    InMemoryRequirementSetRepository,
)
from ats.main import app
from ats.modules.recruitment.application.manage_requirement_sets import (
    CreateRequirementSetInput,
)
from ats.modules.recruitment.application.vacancy_crud import (
    UpdateVacancyInput,
    VacancyCrudUseCase,
)
from ats.modules.recruitment.domain.requirement_set import (
    RequirementOrigin,
    RequirementSet,
    RequirementSetStatus,
)
from ats.modules.recruitment.domain.vacancy import (
    VACANCY_TRANSITIONS,
    InvalidVacancyTransitionError,
    RoleDescription,
    Seniority,
    Vacancy,
    VacancyClosed,
    VacancyPublished,
    VacancyStatus,
    VacancyStatusChanged,
)
from ats.shared.ids import TenantId, VacancyId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def _make_role(
    title: str = "Python Developer",
    seniority: Seniority = Seniority.MIDDLE,
    team: str = "Backend",
    description: str = "Backend developer for FastAPI services",
) -> RoleDescription:
    return RoleDescription(
        title=title,
        seniority=seniority,
        team=team,
        description=description,
        requirements=["Python", "FastAPI"],
        nice_to_have=["Docker"],
    )


# ---------------------------------------------------------------------------
# JUGO-120 + JUGO-124: Домен Vacancy — статусная машина
# ---------------------------------------------------------------------------


class TestVacancyStateMachine:
    """Тесты статусной машины вакансии (JUGO-124)."""

    def test_create_vacancy_has_draft_status(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        assert vacancy.status == VacancyStatus.DRAFT
        assert vacancy.hiring_team == "Backend"
        assert vacancy.hired_count == 0
        assert vacancy.closed_at is None
        assert not vacancy.is_terminal
        assert not vacancy.is_active

    def test_publish_transitions_draft_to_open(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.collect_events()  # clean

        vacancy.publish()

        assert vacancy.status == VacancyStatus.OPEN
        assert vacancy.is_active
        events = vacancy.collect_events()
        event_types = [type(e).__name__ for e in events]
        assert "VacancyPublished" in event_types
        assert "VacancyStatusChanged" in event_types

    def test_publish_without_description_raises(self) -> None:
        role = RoleDescription(
            title="Dev", seniority=Seniority.JUNIOR, team="X", description=""
        )
        vacancy = Vacancy.create(tenant_id=TENANT, role=role)
        with pytest.raises(ValueError, match="role description"):
            vacancy.publish()

    def test_hold_transitions_open_to_on_hold(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        vacancy.collect_events()

        vacancy.put_on_hold()

        assert vacancy.status == VacancyStatus.ON_HOLD
        assert not vacancy.is_active
        events = vacancy.collect_events()
        assert any(isinstance(e, VacancyStatusChanged) for e in events)

    def test_resume_from_hold_to_open(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        vacancy.put_on_hold()

        vacancy.resume_publishing()

        assert vacancy.status == VacancyStatus.OPEN
        assert vacancy.is_active

    def test_close_transitions_open_to_closed(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        vacancy.increment_hired()
        vacancy.collect_events()

        vacancy.close()

        assert vacancy.status == VacancyStatus.CLOSED
        assert vacancy.is_terminal
        assert vacancy.closed_at is not None
        assert vacancy.hired_count == 1
        events = vacancy.collect_events()
        assert any(isinstance(e, VacancyClosed) for e in events)

    def test_close_from_on_hold(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        vacancy.put_on_hold()

        vacancy.close()

        assert vacancy.status == VacancyStatus.CLOSED

    def test_cancel_from_draft(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())

        vacancy.cancel()

        assert vacancy.status == VacancyStatus.CANCELED
        assert vacancy.is_terminal

    def test_cancel_from_open(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()

        vacancy.cancel()

        assert vacancy.status == VacancyStatus.CANCELED

    def test_reopen_closed_vacancy(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        vacancy.close()

        vacancy.resume_publishing()

        assert vacancy.status == VacancyStatus.OPEN
        assert not vacancy.is_terminal

    def test_invalid_transition_draft_to_closed_raises(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        with pytest.raises(InvalidVacancyTransitionError):
            vacancy.close()

    def test_invalid_transition_canceled_to_any_raises(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.cancel()

        with pytest.raises(InvalidVacancyTransitionError):
            vacancy.publish()
        with pytest.raises(InvalidVacancyTransitionError):
            vacancy.put_on_hold()
        with pytest.raises(InvalidVacancyTransitionError):
            vacancy.close()

    def test_transition_idempotent_same_status(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy._transition_to(VacancyStatus.DRAFT)  # no-op
        assert vacancy.status == VacancyStatus.DRAFT

    def test_increment_hired(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        assert vacancy.hired_count == 0
        vacancy.increment_hired()
        vacancy.increment_hired()
        assert vacancy.hired_count == 2

    def test_update_role_patch(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())

        vacancy.update_role(title="Senior Python Developer", hiring_team="Platform")

        assert vacancy.role.title == "Senior Python Developer"
        assert vacancy.hiring_team == "Platform"
        assert vacancy.role.team == "Backend"  # unchanged

    def test_update_role_on_closed_raises(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        vacancy.close()

        with pytest.raises(ValueError, match="closed"):
            vacancy.update_role(title="New Title")

    def test_transition_matrix_completeness(self) -> None:
        """Все статусы представлены в матрице переходов."""
        all_statuses = set(VacancyStatus)
        assert set(VACANCY_TRANSITIONS.keys()) == all_statuses

    def test_published_event_contains_team(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.collect_events()

        vacancy.publish()

        events = vacancy.collect_events()
        published = next(e for e in events if isinstance(e, VacancyPublished))
        assert published.team == "Backend"
        assert published.title == "Python Developer"


# ---------------------------------------------------------------------------
# JUGO-121: Домен RequirementSet
# ---------------------------------------------------------------------------


class TestRequirementSetDomain:
    """Тесты домена версионируемых критериев (JUGO-121)."""

    def test_create_requirement_set(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        criteria = {"summary": "test", "groups": []}

        req_set = RequirementSet.create(
            tenant_id=TENANT,
            vacancy_id=vacancy.id,
            version_number=1,
            criteria=criteria,
            origin=RequirementOrigin.AI,
            provenance_id=uuid4(),
        )

        assert req_set.version_number == 1
        assert req_set.origin == RequirementOrigin.AI
        assert req_set.status == RequirementSetStatus.DRAFT
        assert req_set.criteria == criteria
        assert req_set.provenance_id is not None
        assert not req_set.is_active()

    def test_activate_requirement_set(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        req_set = RequirementSet.create(
            tenant_id=TENANT,
            vacancy_id=vacancy.id,
            version_number=1,
            criteria={"summary": "v1"},
        )

        req_set.activate()

        assert req_set.status == RequirementSetStatus.ACTIVE
        assert req_set.is_active()
        assert req_set.activated_at is not None
        events = req_set.collect_events()
        assert any(e.__class__.__name__ == "RequirementSetActivated" for e in events)

    def test_archive_requirement_set(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        req_set = RequirementSet.create(
            tenant_id=TENANT,
            vacancy_id=vacancy.id,
            version_number=1,
            criteria={"summary": "v1"},
        )
        req_set.activate()

        req_set.archive()

        assert req_set.status == RequirementSetStatus.ARCHIVED
        assert not req_set.is_active()

    def test_manual_origin(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        req_set = RequirementSet.create(
            tenant_id=TENANT,
            vacancy_id=vacancy.id,
            version_number=1,
            criteria={},
            origin=RequirementOrigin.MANUAL,
        )
        assert req_set.origin == RequirementOrigin.MANUAL
        assert req_set.provenance_id is None

    def test_to_dict_serialization(self) -> None:
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        req_set = RequirementSet.create(
            tenant_id=TENANT,
            vacancy_id=vacancy.id,
            version_number=1,
            criteria={"summary": "test"},
            origin=RequirementOrigin.AI_EDITED,
        )

        d = req_set.to_dict()

        assert d["version_number"] == 1
        assert d["origin"] == "ai_edited"
        assert d["status"] == "draft"
        assert d["criteria"] == {"summary": "test"}
        assert "created_at" in d
        assert d["activated_at"] is None


# ---------------------------------------------------------------------------
# Use cases: VacancyCrudUseCase
# ---------------------------------------------------------------------------


class TestVacancyCrudUseCase:
    """Тесты CRUD use case для вакансий (JUGO-120, JUGO-124)."""

    @pytest.mark.asyncio
    async def test_get_not_found(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        crud = VacancyCrudUseCase(InMemoryVacancyRepository())
        result = await crud.get(TENANT, VacancyId(uuid4()))
        assert is_error(result)
        assert result.error.code.value == "not_found"

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        v1 = Vacancy.create(tenant_id=TENANT, role=_make_role(title="Dev 1"))
        v2 = Vacancy.create(tenant_id=TENANT, role=_make_role(title="Dev 2"))
        v2.publish()
        await repo.save(v1)
        await repo.save(v2)

        crud = VacancyCrudUseCase(repo)
        result = await crud.list(TENANT, status=VacancyStatus.OPEN)
        assert not is_error(result)
        assert len(result.value) == 1
        assert result.value[0].status == VacancyStatus.OPEN

    @pytest.mark.asyncio
    async def test_update_vacancy(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await repo.save(vacancy)

        crud = VacancyCrudUseCase(repo)
        result = await crud.update(
            TENANT,
            vacancy.id,
            UpdateVacancyInput(title="Updated Title", hiring_team="New Team"),
        )

        assert not is_error(result)
        assert result.value.role.title == "Updated Title"
        assert result.value.hiring_team == "New Team"

    @pytest.mark.asyncio
    async def test_publish_via_use_case(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await repo.save(vacancy)

        crud = VacancyCrudUseCase(repo)
        result = await crud.publish(TENANT, vacancy.id)

        assert not is_error(result)
        assert result.value.status == VacancyStatus.OPEN

    @pytest.mark.asyncio
    async def test_close_via_use_case(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        await repo.save(vacancy)

        crud = VacancyCrudUseCase(repo)
        result = await crud.close(TENANT, vacancy.id)

        assert not is_error(result)
        assert result.value.status == VacancyStatus.CLOSED
        assert result.value.closed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_via_use_case(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await repo.save(vacancy)

        crud = VacancyCrudUseCase(repo)
        result = await crud.cancel(TENANT, vacancy.id)

        assert not is_error(result)
        assert result.value.status == VacancyStatus.CANCELED

    @pytest.mark.asyncio
    async def test_hold_via_use_case(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        vacancy.publish()
        await repo.save(vacancy)

        crud = VacancyCrudUseCase(repo)
        result = await crud.put_on_hold(TENANT, vacancy.id)

        assert not is_error(result)
        assert result.value.status == VacancyStatus.ON_HOLD

    @pytest.mark.asyncio
    async def test_delete_draft(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository

        repo = InMemoryVacancyRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await repo.save(vacancy)

        crud = VacancyCrudUseCase(repo)
        result = await crud.delete(TENANT, vacancy.id)
        # delete currently returns error (deletion not supported)
        assert is_error(result)


# ---------------------------------------------------------------------------
# Use cases: RequirementSetUseCase
# ---------------------------------------------------------------------------


class TestRequirementSetUseCase:
    """Тесты use case для версионируемых критериев (JUGO-121)."""

    @pytest.mark.asyncio
    async def test_create_requirement_set(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await vacancy_repo.save(vacancy)

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)
        result = await use_case.create(
            TENANT,
            CreateRequirementSetInput(
                vacancy_id=vacancy.id,
                criteria={"summary": "test criteria"},
                origin=RequirementOrigin.AI,
            ),
        )

        assert not is_error(result)
        assert result.value.requirement_set.version_number == 1
        assert result.value.requirement_set.status == RequirementSetStatus.DRAFT

    @pytest.mark.asyncio
    async def test_activate_requirement_set(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await vacancy_repo.save(vacancy)

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)
        create_result = await use_case.create(
            TENANT,
            CreateRequirementSetInput(
                vacancy_id=vacancy.id,
                criteria={"summary": "v1"},
            ),
        )
        set_id = create_result.value.requirement_set.id

        activate_result = await use_case.activate(TENANT, vacancy.id, set_id)

        assert not is_error(activate_result)
        assert activate_result.value.is_active()

    @pytest.mark.asyncio
    async def test_activate_archives_previous_active(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await vacancy_repo.save(vacancy)

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)

        # Создать v1 и активировать
        r1 = await use_case.create(
            TENANT,
            CreateRequirementSetInput(vacancy_id=vacancy.id, criteria={"v": 1}),
        )
        await use_case.activate(TENANT, vacancy.id, r1.value.requirement_set.id)

        # Создать v2 и активировать
        r2 = await use_case.create(
            TENANT,
            CreateRequirementSetInput(vacancy_id=vacancy.id, criteria={"v": 2}),
        )
        await use_case.activate(TENANT, vacancy.id, r2.value.requirement_set.id)

        # v1 должна быть архивирована
        active = await use_case.get_active(TENANT, vacancy.id)
        assert active.value is not None
        assert active.value.version_number == 2

        versions = await use_case.list_versions(TENANT, vacancy.id)
        v1_set = next(v for v in versions.value if v.version_number == 1)
        assert v1_set.status == RequirementSetStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_list_versions(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await vacancy_repo.save(vacancy)

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)
        await use_case.create(
            TENANT,
            CreateRequirementSetInput(vacancy_id=vacancy.id, criteria={"v": 1}),
        )
        await use_case.create(
            TENANT,
            CreateRequirementSetInput(vacancy_id=vacancy.id, criteria={"v": 2}),
        )

        result = await use_case.list_versions(TENANT, vacancy.id)

        assert not is_error(result)
        assert len(result.value) == 2
        assert result.value[0].version_number == 1
        assert result.value[1].version_number == 2

    @pytest.mark.asyncio
    async def test_get_active_returns_none_when_no_active(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()
        vacancy = Vacancy.create(tenant_id=TENANT, role=_make_role())
        await vacancy_repo.save(vacancy)

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)
        await use_case.create(
            TENANT,
            CreateRequirementSetInput(vacancy_id=vacancy.id, criteria={}),
        )

        result = await use_case.get_active(TENANT, vacancy.id)
        assert not is_error(result)
        assert result.value is None

    @pytest.mark.asyncio
    async def test_create_for_nonexistent_vacancy_fails(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)
        result = await use_case.create(
            TENANT,
            CreateRequirementSetInput(
                vacancy_id=VacancyId(uuid4()),
                criteria={},
            ),
        )

        assert is_error(result)
        assert result.error.code.value == "not_found"

    @pytest.mark.asyncio
    async def test_activate_wrong_vacancy_fails(self) -> None:
        from ats.infra.stubs import InMemoryVacancyRepository
        from ats.modules.recruitment.application.manage_requirement_sets import (
            RequirementSetUseCase,
        )

        vacancy_repo = InMemoryVacancyRepository()
        req_repo = InMemoryRequirementSetRepository()
        v1 = Vacancy.create(tenant_id=TENANT, role=_make_role())
        v2 = Vacancy.create(tenant_id=TENANT, role=_make_role(title="Other"))
        await vacancy_repo.save(v1)
        await vacancy_repo.save(v2)

        use_case = RequirementSetUseCase(req_repo, vacancy_repo)
        create_result = await use_case.create(
            TENANT,
            CreateRequirementSetInput(vacancy_id=v1.id, criteria={}),
        )

        # Попытка активировать критерии v1 на вакансии v2
        result = await use_case.activate(
            TENANT, v2.id, create_result.value.requirement_set.id
        )

        assert is_error(result)
        assert result.error.code.value == "validation"


# ---------------------------------------------------------------------------
# REST API тесты
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client():
    """TestClient с свежим контейнером."""
    reset_container()
    return TestClient(app)


class TestVacancyReferencesAPI:
    """JUGO-122: справочники."""

    def test_get_references(self, api_client: TestClient) -> None:
        resp = api_client.get("/api/v1/vacancies/references")
        assert resp.status_code == 200
        data = resp.json()
        assert "seniorities" in data
        assert "statuses" in data
        assert "work_formats" in data
        assert "rejection_reasons" in data
        assert "middle" in data["seniorities"]
        assert "draft" in data["statuses"]
        assert "open" in data["statuses"]
        assert "remote" in data["work_formats"]
        assert "filled_internally" in data["rejection_reasons"]


class TestVacancyStatusMachineAPI:
    """JUGO-124: статусная машина через REST."""

    def _create_vacancy(self, api_client: TestClient) -> str:
        resp = api_client.post(
            "/api/v1/vacancies",
            json={
                "title": "Senior Backend Dev",
                "seniority": "senior",
                "team": "Platform",
                "description": "Backend developer for high-load services",
                "requirements": ["Python", "PostgreSQL"],
                "nice_to_have": ["Kubernetes"],
            },
        )
        assert resp.status_code == 201
        return resp.json()["vacancy_id"]

    def test_publish_vacancy(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        resp = api_client.post(f"/api/v1/vacancies/{vacancy_id}/publish")
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"

    def test_hold_vacancy(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)
        api_client.post(f"/api/v1/vacancies/{vacancy_id}/publish")

        resp = api_client.post(f"/api/v1/vacancies/{vacancy_id}/hold")
        assert resp.status_code == 200
        assert resp.json()["status"] == "on_hold"

    def test_close_vacancy(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)
        api_client.post(f"/api/v1/vacancies/{vacancy_id}/publish")

        resp = api_client.post(f"/api/v1/vacancies/{vacancy_id}/close")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"
        assert resp.json()["closed_at"] is not None

    def test_cancel_vacancy(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        resp = api_client.post(f"/api/v1/vacancies/{vacancy_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled"

    def test_invalid_transition_returns_400(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        # draft → close is invalid
        resp = api_client.post(f"/api/v1/vacancies/{vacancy_id}/close")
        assert resp.status_code == 400

    def test_get_vacancy(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        resp = api_client.get(f"/api/v1/vacancies/{vacancy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == vacancy_id
        assert data["status"] == "draft"
        assert data["title"] == "Senior Backend Dev"
        assert data["hiring_team"] == "Platform"
        assert data["hired_count"] == 0

    def test_get_vacancy_not_found(self, api_client: TestClient) -> None:
        resp = api_client.get(f"/api/v1/vacancies/{uuid4()}")
        assert resp.status_code == 404

    def test_list_vacancies(self, api_client: TestClient) -> None:
        self._create_vacancy(api_client)
        self._create_vacancy(api_client)

        resp = api_client.get("/api/v1/vacancies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    def test_list_vacancies_with_status_filter(self, api_client: TestClient) -> None:
        vid = self._create_vacancy(api_client)
        api_client.post(f"/api/v1/vacancies/{vid}/publish")

        resp = api_client.get("/api/v1/vacancies?status=open")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["status"] == "open" for item in data["items"])

    def test_patch_vacancy(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        resp = api_client.patch(
            f"/api/v1/vacancies/{vacancy_id}",
            json={"title": "Updated Title", "hiring_team": "New Team"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"
        assert resp.json()["hiring_team"] == "New Team"


class TestRequirementSetAPI:
    """JUGO-121 + JUGO-122: наборы критериев через REST."""

    def _create_vacancy(self, api_client: TestClient) -> str:
        resp = api_client.post(
            "/api/v1/vacancies",
            json={
                "title": "DevOps Engineer",
                "seniority": "middle",
                "team": "Infra",
                "description": "DevOps для CI/CD и Kubernetes",
            },
        )
        return resp.json()["vacancy_id"]

    def test_create_requirement_set(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        resp = api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={
                "criteria": {"summary": "DevOps criteria", "groups": []},
                "origin": "manual",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version_number"] == 1
        assert data["status"] == "draft"
        assert data["origin"] == "manual"

    def test_activate_requirement_set(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        create_resp = api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={"criteria": {"summary": "v1"}, "origin": "ai"},
        )
        set_id = create_resp.json()["id"]

        resp = api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements/{set_id}/activate"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        assert resp.json()["activated_at"] is not None

    def test_list_requirement_sets(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={"criteria": {"v": 1}, "origin": "ai"},
        )
        api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={"criteria": {"v": 2}, "origin": "manual"},
        )

        resp = api_client.get(f"/api/v1/vacancies/{vacancy_id}/requirements")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["items"][0]["version_number"] == 1
        assert data["items"][1]["version_number"] == 2

    def test_get_active_requirement_set(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        create_resp = api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={"criteria": {"summary": "active version"}, "origin": "ai"},
        )
        set_id = create_resp.json()["id"]
        api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements/{set_id}/activate"
        )

        resp = api_client.get(f"/api/v1/vacancies/{vacancy_id}/requirements/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["criteria"]["summary"] == "active version"

    def test_get_active_returns_none_when_no_active(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        resp = api_client.get(f"/api/v1/vacancies/{vacancy_id}/requirements/active")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_activate_archives_previous(self, api_client: TestClient) -> None:
        vacancy_id = self._create_vacancy(api_client)

        # v1
        r1 = api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={"criteria": {"v": 1}, "origin": "ai"},
        )
        api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements/{r1.json()['id']}/activate"
        )

        # v2
        r2 = api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements",
            json={"criteria": {"v": 2}, "origin": "manual"},
        )
        api_client.post(
            f"/api/v1/vacancies/{vacancy_id}/requirements/{r2.json()['id']}/activate"
        )

        # Активная — v2
        active = api_client.get(
            f"/api/v1/vacancies/{vacancy_id}/requirements/active"
        )
        assert active.json()["version_number"] == 2

        # v1 — архивная
        versions = api_client.get(
            f"/api/v1/vacancies/{vacancy_id}/requirements"
        )
        v1_item = next(
            v for v in versions.json()["items"] if v["version_number"] == 1
        )
        assert v1_item["status"] == "archived"

    def test_create_requirement_set_for_nonexistent_vacancy(
        self, api_client: TestClient
    ) -> None:
        resp = api_client.post(
            f"/api/v1/vacancies/{uuid4()}/requirements",
            json={"criteria": {}, "origin": "manual"},
        )
        assert resp.status_code == 404
