"""Тесты модуля candidates: домен, CRUD, факты, теги, blacklist, массовый импорт."""

from __future__ import annotations

import pytest

from ats.infra.container import build_container
from ats.modules.candidates.application.candidate_crud import (
    AddBlacklistInput,
    AddFactInput,
    AddTagInput,
    BulkImportRow,
    CreateCandidateInput,
    UpdateCandidateInput,
)
from ats.modules.candidates.domain.candidate import (
    Candidate,
    CandidateCreated,
    CandidateSource,
    CandidateUpdated,
    ResumeAttached,
)
from ats.modules.candidates.domain.facts import (
    FactSource,
    FactType,
    build_experience_fact,
    build_skill_fact,
)
from ats.modules.candidates.domain.tags import BlacklistReason
from ats.shared.ids import CandidateId, TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Domain: Candidate aggregate
# ---------------------------------------------------------------------------


class TestCandidateAggregate:
    def test_create_publishes_candidate_created_event(self) -> None:
        candidate = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Python Developer",
            skills=["Python", "FastAPI"],
            location="Москва",
        )
        events = candidate.collect_events()

        assert len(events) == 1
        assert isinstance(events[0], CandidateCreated)
        assert events[0].full_name == "Иван Иванов"
        assert events[0].source == "direct"
        assert candidate.location == "Москва"
        assert candidate.skills == ["Python", "FastAPI"]

    def test_create_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="full_name is required"):
            Candidate.create(tenant_id=TENANT, full_name="  ", source=CandidateSource.DIRECT)

    def test_update_profile_changes_fields_and_publishes_event(self) -> None:
        candidate = Candidate.create(
            tenant_id=TENANT, full_name="Иван", source=CandidateSource.DIRECT
        )
        candidate.collect_events()  # clean

        candidate.update_profile(
            full_name="Иван Петров",
            headline="Senior Developer",
            skills=["Python", "Django"],
            location="Санкт-Петербург",
        )
        events = candidate.collect_events()

        assert candidate.full_name == "Иван Петров"
        assert candidate.headline == "Senior Developer"
        assert candidate.skills == ["Python", "Django"]
        assert candidate.location == "Санкт-Петербург"
        assert len(events) == 1
        assert isinstance(events[0], CandidateUpdated)
        assert set(events[0].fields_changed) == {"full_name", "headline", "skills", "location"}

    def test_update_profile_no_changes_no_event(self) -> None:
        candidate = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван",
            source=CandidateSource.DIRECT,
            headline="Dev",
        )
        candidate.collect_events()

        candidate.update_profile(full_name="Иван", headline="Dev")
        events = candidate.collect_events()

        assert len(events) == 0

    def test_update_profile_rejects_empty_name(self) -> None:
        candidate = Candidate.create(
            tenant_id=TENANT, full_name="Иван", source=CandidateSource.DIRECT
        )
        candidate.update_profile(full_name="   ")
        assert candidate.full_name == "Иван"

    def test_attach_resume_publishes_event(self) -> None:
        from uuid import uuid4

        candidate = Candidate.create(
            tenant_id=TENANT, full_name="Иван", source=CandidateSource.DIRECT
        )
        candidate.collect_events()

        provenance = uuid4()
        candidate.attach_resume(provenance)

        assert candidate.resume_provenance == provenance
        events = candidate.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], ResumeAttached)

    def test_to_registry_dict(self) -> None:
        candidate = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван",
            source=CandidateSource.DIRECT,
            headline="Dev",
            skills=["Python"],
            location="Москва",
        )
        d = candidate.to_registry_dict()

        assert d["full_name"] == "Иван"
        assert d["source"] == "direct"
        assert d["location"] == "Москва"
        assert d["skills"] == ["Python"]
        assert d["resume_provenance"] is None


# ---------------------------------------------------------------------------
# Domain: Facts
# ---------------------------------------------------------------------------


class TestCandidateFacts:
    def test_build_experience_fact(self) -> None:
        from datetime import date

        fact = build_experience_fact(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            company="Yandex",
            position="Senior Developer",
            start_date=date(2020, 1, 1),
        )
        assert fact.fact_type == FactType.EXPERIENCE
        assert fact.content["company"] == "Yandex"
        assert fact.content["position"] == "Senior Developer"

    def test_build_skill_fact(self) -> None:
        fact = build_skill_fact(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            skill_name="Python",
            level="expert",
        )
        assert fact.fact_type == FactType.SKILL
        assert fact.content["skill_name"] == "Python"
        assert fact.content["level"] == "expert"

    def test_pinned_fact_cannot_be_overwritten(self) -> None:
        fact = build_skill_fact(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            skill_name="Python",
        )
        fact.pinned = True
        assert not fact.can_be_overwritten_by(FactSource.RESUME_VERSION)
        assert not fact.can_be_overwritten_by(FactSource.AI_INFERENCE)

    def test_manual_fact_not_overwritten_by_auto_sources(self) -> None:
        fact = build_skill_fact(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            skill_name="Python",
            source=FactSource.MANUAL,
        )
        assert not fact.can_be_overwritten_by(FactSource.RESUME_VERSION)
        assert not fact.can_be_overwritten_by(FactSource.AI_INFERENCE)

    def test_resume_fact_overwritten_by_manual(self) -> None:
        fact = build_skill_fact(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            skill_name="Python",
            source=FactSource.RESUME_VERSION,
        )
        assert fact.can_be_overwritten_by(FactSource.MANUAL)


# ---------------------------------------------------------------------------
# Domain: Tags & Blacklist
# ---------------------------------------------------------------------------


class TestTagsAndBlacklist:
    def test_blacklist_reason_is_enum(self) -> None:
        assert BlacklistReason.FALSIFIED_DOCUMENTS.value == "falsified_documents"
        assert BlacklistReason.SECURITY_VIOLATION.value == "security_violation"

    def test_tag_creation(self) -> None:
        from uuid import uuid4

        from ats.modules.candidates.domain.tags import CandidateTag, TagId

        tag = CandidateTag(
            id=TagId(uuid4()),
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            name="hot_lead",
            color="#ff0000",
        )
        assert tag.name == "hot_lead"
        assert tag.color == "#ff0000"


# ---------------------------------------------------------------------------
# Use case: CRUD
# ---------------------------------------------------------------------------


class TestCandidateCrudUseCase:
    @pytest.mark.asyncio
    async def test_create_candidate(self) -> None:
        crud = build_container().candidate_crud
        result = await crud.create(
            TENANT,
            CreateCandidateInput(
                full_name="Анна Смирнова",
                source=CandidateSource.DIRECT,
                headline="QA Engineer",
                skills=["Selenium", "Python"],
                location="Казань",
            ),
        )
        assert not is_error(result)
        assert result.value.full_name == "Анна Смирнова"
        assert result.value.location == "Казань"

    @pytest.mark.asyncio
    async def test_create_rejects_empty_name(self) -> None:
        crud = build_container().candidate_crud
        result = await crud.create(TENANT, CreateCandidateInput(full_name=""))
        assert is_error(result)
        assert result.error.code.value == "validation"

    @pytest.mark.asyncio
    async def test_get_candidate(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(
            TENANT, CreateCandidateInput(full_name="Пётр", source=CandidateSource.REFERRAL)
        )
        fetched = await crud.get(TENANT, created.value.id)
        assert not is_error(fetched)
        assert fetched.value.full_name == "Пётр"
        assert fetched.value.source == CandidateSource.REFERRAL

    @pytest.mark.asyncio
    async def test_get_not_found(self) -> None:
        crud = build_container().candidate_crud
        result = await crud.get(TENANT, CandidateId.generate())
        assert is_error(result)
        assert result.error.code.value == "not_found"

    @pytest.mark.asyncio
    async def test_update_candidate(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Старое Имя"))
        result = await crud.update(
            TENANT,
            created.value.id,
            UpdateCandidateInput(full_name="Новое Имя", location="Москва"),
        )
        assert not is_error(result)
        assert result.value.full_name == "Новое Имя"
        assert result.value.location == "Москва"

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        crud = build_container().candidate_crud
        result = await crud.update(
            TENANT, CandidateId.generate(), UpdateCandidateInput(full_name="X")
        )
        assert is_error(result)
        assert result.error.code.value == "not_found"

    @pytest.mark.asyncio
    async def test_list_candidates(self) -> None:
        crud = build_container().candidate_crud
        await crud.create(TENANT, CreateCandidateInput(full_name="А"))
        await crud.create(TENANT, CreateCandidateInput(full_name="Б"))
        result = await crud.list(TENANT, limit=10)
        assert not is_error(result)
        assert len(result.value) >= 2

    @pytest.mark.asyncio
    async def test_list_pagination(self) -> None:
        crud = build_container().candidate_crud
        for i in range(5):
            await crud.create(TENANT, CreateCandidateInput(full_name=f"C{i}"))
        result = await crud.list(TENANT, limit=2, offset=0)
        assert not is_error(result)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    async def test_delete_candidate(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Удаляемый"))
        result = await crud.delete(TENANT, created.value.id)
        assert not is_error(result)
        assert result.value is True
        # Verify gone
        fetched = await crud.get(TENANT, created.value.id)
        assert is_error(fetched)

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        crud = build_container().candidate_crud
        result = await crud.delete(TENANT, CandidateId.generate())
        assert is_error(result)


# ---------------------------------------------------------------------------
# Use case: Facts
# ---------------------------------------------------------------------------


class TestCandidateFactsUseCase:
    @pytest.mark.asyncio
    async def test_add_and_list_fact(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Иван"))
        fact_result = await crud.add_fact(
            TENANT,
            created.value.id,
            AddFactInput(
                fact_type=FactType.EXPERIENCE,
                source=FactSource.MANUAL,
                content={"company": "Google", "position": "SRE"},
            ),
        )
        assert not is_error(fact_result)
        assert fact_result.value.fact_type == FactType.EXPERIENCE

        list_result = await crud.list_facts(TENANT, created.value.id)
        assert not is_error(list_result)
        assert len(list_result.value) == 1

    @pytest.mark.asyncio
    async def test_delete_fact(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Иван"))
        fact_result = await crud.add_fact(
            TENANT,
            created.value.id,
            AddFactInput(fact_type=FactType.SKILL, content={"skill_name": "Python"}),
        )
        fact_id = str(fact_result.value.id.value)
        del_result = await crud.delete_fact(TENANT, created.value.id, fact_id)
        assert not is_error(del_result)
        assert del_result.value is True

    @pytest.mark.asyncio
    async def test_add_fact_candidate_not_found(self) -> None:
        crud = build_container().candidate_crud
        result = await crud.add_fact(
            TENANT,
            CandidateId.generate(),
            AddFactInput(fact_type=FactType.SKILL, content={}),
        )
        assert is_error(result)
        assert result.error.code.value == "not_found"


# ---------------------------------------------------------------------------
# Use case: Tags
# ---------------------------------------------------------------------------


class TestCandidateTagsUseCase:
    @pytest.mark.asyncio
    async def test_add_and_list_tag(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Мария"))
        tag_result = await crud.add_tag(
            TENANT, created.value.id, AddTagInput(name="vip", color="#gold")
        )
        assert not is_error(tag_result)
        assert tag_result.value.name == "vip"

        list_result = await crud.list_tags(TENANT, created.value.id)
        assert not is_error(list_result)
        assert len(list_result.value) == 1

    @pytest.mark.asyncio
    async def test_remove_tag(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Мария"))
        tag_result = await crud.add_tag(TENANT, created.value.id, AddTagInput(name="vip"))
        tag_id = str(tag_result.value.id.value)
        del_result = await crud.remove_tag(TENANT, created.value.id, tag_id)
        assert not is_error(del_result)
        assert del_result.value is True


# ---------------------------------------------------------------------------
# Use case: Blacklist
# ---------------------------------------------------------------------------


class TestCandidateBlacklistUseCase:
    @pytest.mark.asyncio
    async def test_add_to_blacklist(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Блокируемый"))
        result = await crud.add_to_blacklist(
            TENANT,
            created.value.id,
            AddBlacklistInput(reason=BlacklistReason.SECURITY_VIOLATION, note="test"),
        )
        assert not is_error(result)
        assert result.value.reason == BlacklistReason.SECURITY_VIOLATION

    @pytest.mark.asyncio
    async def test_double_blacklist_conflict(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Блок"))
        await crud.add_to_blacklist(
            TENANT, created.value.id, AddBlacklistInput(reason=BlacklistReason.OTHER)
        )
        result = await crud.add_to_blacklist(
            TENANT, created.value.id, AddBlacklistInput(reason=BlacklistReason.OTHER)
        )
        assert is_error(result)
        assert result.error.code.value == "conflict"

    @pytest.mark.asyncio
    async def test_get_blacklist_status(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Блок"))
        # Not blacklisted yet
        status_result = await crud.get_blacklist_status(TENANT, created.value.id)
        assert not is_error(status_result)
        assert status_result.value is None

        await crud.add_to_blacklist(
            TENANT, created.value.id, AddBlacklistInput(reason=BlacklistReason.POLICY_VIOLATION)
        )
        status_result = await crud.get_blacklist_status(TENANT, created.value.id)
        assert not is_error(status_result)
        assert status_result.value is not None
        assert status_result.value.reason == BlacklistReason.POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_remove_from_blacklist(self) -> None:
        crud = build_container().candidate_crud
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Блок"))
        await crud.add_to_blacklist(
            TENANT, created.value.id, AddBlacklistInput(reason=BlacklistReason.OTHER)
        )
        result = await crud.remove_from_blacklist(TENANT, created.value.id)
        assert not is_error(result)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_is_blacklisted(self) -> None:
        container = build_container()
        crud = container.candidate_crud
        repo = container.candidate_repository
        created = await crud.create(TENANT, CreateCandidateInput(full_name="Блок"))
        assert not await repo.is_blacklisted(TENANT, created.value.id)
        await crud.add_to_blacklist(
            TENANT, created.value.id, AddBlacklistInput(reason=BlacklistReason.OTHER)
        )
        assert await repo.is_blacklisted(TENANT, created.value.id)


# ---------------------------------------------------------------------------
# Use case: Bulk import
# ---------------------------------------------------------------------------


class TestBulkImportCandidatesUseCase:
    @pytest.mark.asyncio
    async def test_bulk_import_creates_all(self) -> None:
        container = build_container()
        result = await container.bulk_import_candidates.execute(
            TENANT,
            [
                BulkImportRow(full_name="Кандидат 1", location="Москва"),
                BulkImportRow(full_name="Кандидат 2", location="Казань"),
                BulkImportRow(full_name="Кандидат 3", location="Уфа"),
            ],
        )
        assert not is_error(result)
        assert len(result.value.created) == 3
        assert len(result.value.errors) == 0

    @pytest.mark.asyncio
    async def test_bulk_import_with_errors(self) -> None:
        container = build_container()
        result = await container.bulk_import_candidates.execute(
            TENANT,
            [
                BulkImportRow(full_name="Хороший"),
                BulkImportRow(full_name=""),  # empty name → error
                BulkImportRow(full_name="Тоже хороший"),
            ],
        )
        assert not is_error(result)
        assert len(result.value.created) == 2
        assert len(result.value.errors) == 1

    @pytest.mark.asyncio
    async def test_bulk_import_empty_list(self) -> None:
        container = build_container()
        result = await container.bulk_import_candidates.execute(TENANT, [])
        assert is_error(result)
        assert result.error.code.value == "validation"

    @pytest.mark.asyncio
    async def test_bulk_import_with_skills(self) -> None:
        container = build_container()
        result = await container.bulk_import_candidates.execute(
            TENANT,
            [BulkImportRow(full_name="Скилловый", skills=["Python", "SQL"])],
        )
        assert not is_error(result)
        candidate = result.value.created[0]
        assert candidate.skills == ["Python", "SQL"]
