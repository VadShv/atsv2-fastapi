"""Тесты дедупликации кандидатов (JUGO-150..155).

Покрытие:
- Домен: hash_contact, normalize_contact, MergeLog.create/rollback/is_rollbackable
- Fuzzy scoring: score_pair, classify_score, find_fuzzy_duplicates
- Use cases: register_contact, find_exact_duplicates, check_contact_exists,
  find_fuzzy_duplicates, merge_candidates, rollback_merge, auto_merge_exact
- API: все 8 endpoints
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.modules.candidates.application.fuzzy_scoring import (
    classify_score,
    find_fuzzy_duplicates,
    score_pair,
)
from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
from ats.modules.candidates.domain.dedup import (
    ContactHash,
    ContactKind,
    DuplicateConfidence,
    MergeLog,
    MergeStatus,
    hash_contact,
    normalize_contact,
)
from ats.modules.candidates.domain.facts import (
    CandidateFact,
    FactId,
    FactSource,
    FactType,
)
from ats.modules.candidates.domain.tags import CandidateTag, TagId
from ats.modules.recruitment.domain.application import Application, ApplicationOrigin
from ats.shared.ids import CandidateId, TenantId, VacancyId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")
client = TestClient(app)


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_candidate(
    name: str = "Иван Иванов",
    headline: str = "Python Developer born 1990",
    location: str = "Москва",
) -> Candidate:
    container = get_container()
    c = Candidate.create(
        tenant_id=TENANT,
        full_name=name,
        source=CandidateSource.DIRECT,
        headline=headline,
        skills=["Python"],
        location=location,
    )
    asyncio.run(container.candidate_repository.save(c))
    return c


def _register_contact(candidate: Candidate, kind: ContactKind, value: str) -> None:
    container = get_container()
    asyncio.run(
        container.dedup_use_case.register_contact(
            TENANT, candidate.id, kind, value
        )
    )


# ---------------------------------------------------------------------------
# Domain: hash_contact / normalize_contact (JUGO-150)
# ---------------------------------------------------------------------------


class TestNormalizeContact:
    def test_phone_strips_non_digits(self) -> None:
        assert normalize_contact(ContactKind.PHONE, "+7 (999) 123-45-67") == "79991234567"

    def test_email_lowercase_trim(self) -> None:
        assert normalize_contact(ContactKind.EMAIL, "  John.Doe@Example.COM ") == "john.doe@example.com"

    def test_telegram_lowercase(self) -> None:
        assert normalize_contact(ContactKind.TELEGRAM, "@JohnDoe") == "@johndoe"

    def test_other_lowercase_trim(self) -> None:
        assert normalize_contact(ContactKind.OTHER, "  SomeValue ") == "somevalue"


class TestHashContact:
    def test_same_value_produces_same_hash(self) -> None:
        h1 = hash_contact(ContactKind.EMAIL, "user@example.com")
        h2 = hash_contact(ContactKind.EMAIL, "user@example.com")
        assert h1 == h2

    def test_different_kinds_produce_different_hashes(self) -> None:
        h_email = hash_contact(ContactKind.EMAIL, "user@example.com")
        h_phone = hash_contact(ContactKind.PHONE, "user@example.com")
        assert h_email != h_phone

    def test_phone_normalization_before_hash(self) -> None:
        h1 = hash_contact(ContactKind.PHONE, "+7 (999) 123-45-67")
        h2 = hash_contact(ContactKind.PHONE, "79991234567")
        assert h1 == h2

    def test_email_normalization_before_hash(self) -> None:
        h1 = hash_contact(ContactKind.EMAIL, "USER@EXAMPLE.COM")
        h2 = hash_contact(ContactKind.EMAIL, "user@example.com")
        assert h1 == h2

    def test_different_values_produce_different_hashes(self) -> None:
        h1 = hash_contact(ContactKind.EMAIL, "a@example.com")
        h2 = hash_contact(ContactKind.EMAIL, "b@example.com")
        assert h1 != h2

    def test_hash_is_hex_string(self) -> None:
        h = hash_contact(ContactKind.PHONE, "12345")
        assert len(h) == 64  # SHA-256 hex
        int(h, 16)  # валидный hex


class TestContactHash:
    def test_create_contact_hash(self) -> None:
        ch = ContactHash(
            candidate_id=uuid4(),
            tenant_id=uuid4(),
            kind=ContactKind.EMAIL,
            value_hash="abc123",
            is_primary=True,
        )
        assert ch.kind == ContactKind.EMAIL
        assert ch.is_primary is True
        assert ch.value_hash == "abc123"


# ---------------------------------------------------------------------------
# Domain: MergeLog (JUGO-152, JUGO-153)
# ---------------------------------------------------------------------------


class TestMergeLog:
    def test_create_merge_log(self) -> None:
        survivor_id = CandidateId.generate()
        absorbed_id = CandidateId.generate()
        snapshot = {
            "survivor": {"id": str(survivor_id.value)},
            "absorbed": {"id": str(absorbed_id.value)},
        }

        log = MergeLog.create(
            tenant_id=TENANT,
            survivor_id=survivor_id,
            absorbed_id=absorbed_id,
            snapshot=snapshot,
        )
        assert log.status == MergeStatus.MERGED
        assert log.rolled_back_at is None
        assert log.is_rollbackable is True
        events = log.collect_events()
        assert len(events) == 1

    def test_rollback_within_window(self) -> None:
        survivor_id = CandidateId.generate()
        absorbed_id = CandidateId.generate()
        log = MergeLog.create(
            tenant_id=TENANT,
            survivor_id=survivor_id,
            absorbed_id=absorbed_id,
            snapshot={},
        )
        log.rollback()
        assert log.status == MergeStatus.ROLLED_BACK
        assert log.rolled_back_at is not None
        assert log.is_rollbackable is False
        # collect_events returns all pending events (CandidateMerged + MergeRolledBack)
        events = log.collect_events()
        assert any(type(e).__name__ == "MergeRolledBack" for e in events)

    def test_rollback_expired_raises(self) -> None:
        survivor_id = CandidateId.generate()
        absorbed_id = CandidateId.generate()
        log = MergeLog.create(
            tenant_id=TENANT,
            survivor_id=survivor_id,
            absorbed_id=absorbed_id,
            snapshot={},
        )
        log.expires_at = datetime.now(UTC) - timedelta(days=1)
        with pytest.raises(ValueError, match="истекло|истёк"):
            log.rollback()

    def test_double_rollback_raises(self) -> None:
        survivor_id = CandidateId.generate()
        absorbed_id = CandidateId.generate()
        log = MergeLog.create(
            tenant_id=TENANT,
            survivor_id=survivor_id,
            absorbed_id=absorbed_id,
            snapshot={},
        )
        log.rollback()
        with pytest.raises(ValueError, match="уже откачен"):
            log.rollback()

    def test_get_snapshot_returns_dict(self) -> None:
        snapshot = {"key": "value", "nested": {"a": 1}}
        log = MergeLog.create(
            tenant_id=TENANT,
            survivor_id=CandidateId.generate(),
            absorbed_id=CandidateId.generate(),
            snapshot=snapshot,
        )
        result = log.get_snapshot()
        assert result["key"] == "value"
        assert result["nested"]["a"] == 1


# ---------------------------------------------------------------------------
# Fuzzy scoring (JUGO-151)
# ---------------------------------------------------------------------------


class TestScorePair:
    def test_identical_candidates_high_score(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Developer born 1990",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Developer born 1990",
            location="Москва",
        )
        score, matched = score_pair(a, b)
        assert score >= 95.0
        assert "full_name" in matched
        assert "location" in matched

    def test_different_names_lower_score(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Пётр Петров",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        score, _ = score_pair(a, b)
        assert score < 95.0

    def test_different_location_reduces_score(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Санкт-Петербург",
        )
        score, matched = score_pair(a, b)
        assert "location" not in matched

    def test_completely_different_candidates_low_score(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev A born 1985",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Сидор Сидоров",
            source=CandidateSource.DIRECT,
            headline="Dev B born 2000",
            location="Казань",
        )
        score, _ = score_pair(a, b)
        assert score < 50.0

    def test_score_clamped_to_100(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="А",
            source=CandidateSource.DIRECT,
            headline="X born 1990",
            location="Y",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="А",
            source=CandidateSource.DIRECT,
            headline="X born 1990",
            location="Y",
        )
        score, _ = score_pair(a, b)
        assert score <= 100.0


class TestClassifyScore:
    def test_high_threshold(self) -> None:
        assert classify_score(95.0) == DuplicateConfidence.HIGH
        assert classify_score(100.0) == DuplicateConfidence.HIGH

    def test_medium_threshold(self) -> None:
        assert classify_score(85.0) == DuplicateConfidence.MEDIUM
        assert classify_score(94.9) == DuplicateConfidence.MEDIUM

    def test_low_below_threshold(self) -> None:
        assert classify_score(84.9) == DuplicateConfidence.LOW
        assert classify_score(0.0) == DuplicateConfidence.LOW


class TestFindFuzzyDuplicates:
    def test_finds_duplicates_above_threshold(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        c = Candidate.create(
            tenant_id=TENANT,
            full_name="Уникальный Человек",
            source=CandidateSource.DIRECT,
            headline="Unique born 1970",
            location="Самара",
        )
        matches = find_fuzzy_duplicates([a, b, c], threshold=85.0)
        assert len(matches) == 1
        assert matches[0].score >= 85.0

    def test_no_duplicates_returns_empty(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev A born 1985",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Пётр Петров",
            source=CandidateSource.DIRECT,
            headline="Dev B born 2000",
            location="Казань",
        )
        matches = find_fuzzy_duplicates([a, b], threshold=85.0)
        assert len(matches) == 0

    def test_survivor_is_older_candidate(self) -> None:
        a = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        b = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DIRECT,
            headline="Dev born 1990",
            location="Москва",
        )
        matches = find_fuzzy_duplicates([a, b], threshold=85.0)
        if matches:
            assert matches[0].survivor_id == a.id.value


# ---------------------------------------------------------------------------
# Use cases: JUGO-150 (exact dedup)
# ---------------------------------------------------------------------------


class TestRegisterContact:
    def test_register_contact_returns_hash(self) -> None:
        container = get_container()
        c = _save_candidate()
        result = asyncio.run(
            container.dedup_use_case.register_contact(
                TENANT, c.id, ContactKind.EMAIL, "user@example.com"
            )
        )
        assert not is_error(result)
        assert result.value.value_hash
        assert result.value.kind == ContactKind.EMAIL

    def test_register_empty_value_returns_error(self) -> None:
        container = get_container()
        c = _save_candidate()
        result = asyncio.run(
            container.dedup_use_case.register_contact(
                TENANT, c.id, ContactKind.EMAIL, "  "
            )
        )
        assert is_error(result)


class TestFindExactDuplicates:
    def test_finds_duplicate_by_email(self) -> None:
        c1 = _save_candidate("Иван Иванов")
        c2 = _save_candidate("Иван Иванов Дубль")
        _register_contact(c1, ContactKind.EMAIL, "dup@example.com")
        _register_contact(c2, ContactKind.EMAIL, "dup@example.com")

        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_exact_duplicates(TENANT, c1.id)
        )
        assert len(matches) == 1
        assert matches[0].confidence == DuplicateConfidence.EXACT
        assert matches[0].score == 100.0

    def test_no_duplicates_returns_empty(self) -> None:
        c1 = _save_candidate("Иван")
        _register_contact(c1, ContactKind.EMAIL, "unique@example.com")

        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_exact_duplicates(TENANT, c1.id)
        )
        assert len(matches) == 0

    def test_no_contacts_returns_empty(self) -> None:
        c1 = _save_candidate()
        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_exact_duplicates(TENANT, c1.id)
        )
        assert len(matches) == 0

    def test_phone_normalization_in_dedup(self) -> None:
        c1 = _save_candidate("А")
        c2 = _save_candidate("Б")
        _register_contact(c1, ContactKind.PHONE, "+7 (999) 123-45-67")
        _register_contact(c2, ContactKind.PHONE, "79991234567")

        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_exact_duplicates(TENANT, c1.id)
        )
        assert len(matches) == 1


class TestCheckContactExists:
    def test_existing_contact_returns_ids(self) -> None:
        c = _save_candidate()
        _register_contact(c, ContactKind.EMAIL, "exists@example.com")

        container = get_container()
        ids = asyncio.run(
            container.dedup_use_case.check_contact_exists(
                TENANT, ContactKind.EMAIL, "exists@example.com"
            )
        )
        assert len(ids) == 1
        assert ids[0].value == c.id.value

    def test_nonexistent_contact_returns_empty(self) -> None:
        container = get_container()
        ids = asyncio.run(
            container.dedup_use_case.check_contact_exists(
                TENANT, ContactKind.EMAIL, "nonexistent@example.com"
            )
        )
        assert len(ids) == 0

    def test_normalization_applied(self) -> None:
        c = _save_candidate()
        _register_contact(c, ContactKind.EMAIL, "Test@Example.COM")

        container = get_container()
        ids = asyncio.run(
            container.dedup_use_case.check_contact_exists(
                TENANT, ContactKind.EMAIL, "test@example.com"
            )
        )
        assert len(ids) == 1


# ---------------------------------------------------------------------------
# Use cases: JUGO-151 (fuzzy dedup)
# ---------------------------------------------------------------------------


class TestFindFuzzyDuplicatesUseCase:
    def test_finds_fuzzy_duplicate(self) -> None:
        c1 = _save_candidate("Иван Иванов", "Python Developer born 1990", "Москва")
        c2 = _save_candidate("Иван Иванов", "Python Developer born 1990", "Москва")

        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_fuzzy_duplicates(TENANT, c1.id)
        )
        assert len(matches) >= 1
        assert matches[0].score >= 85.0

    def test_no_fuzzy_duplicates(self) -> None:
        c1 = _save_candidate("Иван Иванов", "Dev A born 1985", "Москва")
        c2 = _save_candidate("Пётр Петров", "Dev B born 2000", "Казань")

        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_fuzzy_duplicates(TENANT, c1.id)
        )
        assert len(matches) == 0

    def test_nonexistent_candidate_returns_empty(self) -> None:
        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_fuzzy_duplicates(
                TENANT, CandidateId.generate()
            )
        )
        assert len(matches) == 0


class TestFindAllDuplicates:
    def test_finds_all_pairs(self) -> None:
        _save_candidate("Иван Иванов", "Dev born 1990", "Москва")
        _save_candidate("Иван Иванов", "Dev born 1990", "Москва")
        _save_candidate("Уникальный", "Other born 1970", "Самара")

        container = get_container()
        matches = asyncio.run(
            container.dedup_use_case.find_all_duplicates(TENANT, limit=100)
        )
        assert len(matches) >= 1


# ---------------------------------------------------------------------------
# Use cases: JUGO-152 (merge)
# ---------------------------------------------------------------------------


class TestMergeCandidates:
    def test_merge_transfers_applications(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        vacancy_id = VacancyId.generate()
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=absorbed.id,
            vacancy_id=vacancy_id,
            origin=ApplicationOrigin.INCOMING,
        )
        asyncio.run(container.application_repository.save(app))

        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        assert not is_error(result)
        assert result.value.transferred_applications == 1

        apps = asyncio.run(
            container.application_repository.list_by_candidate(TENANT, survivor.id)
        )
        assert len(apps) == 1

        deleted = asyncio.run(
            container.candidate_repository.get(TENANT, absorbed.id)
        )
        assert deleted is None

    def test_merge_transfers_facts(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        fact = CandidateFact(
            id=FactId(value=uuid4()),
            tenant_id=TENANT,
            candidate_id=absorbed.id,
            fact_type=FactType.EXPERIENCE,
            source=FactSource.MANUAL,
            content={"company": "TestCorp", "years": 3},
        )
        asyncio.run(container.candidate_repository.add_fact(fact))

        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        assert not is_error(result)
        assert result.value.transferred_facts == 1

        facts = asyncio.run(
            container.candidate_repository.list_facts(TENANT, survivor.id)
        )
        assert len(facts) == 1

    def test_merge_transfers_tags(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        tag = CandidateTag(
            id=TagId(value=uuid4()),
            tenant_id=TENANT,
            candidate_id=absorbed.id,
            name="VIP",
            color="#ff0000",
        )
        asyncio.run(container.candidate_repository.add_tag(tag))

        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        assert not is_error(result)
        assert result.value.transferred_tags == 1

        tags = asyncio.run(
            container.candidate_repository.list_tags(TENANT, survivor.id)
        )
        assert any(t.name == "VIP" for t in tags)

    def test_merge_transfers_contact_hashes(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")
        _register_contact(absorbed, ContactKind.EMAIL, "absorbed@example.com")

        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        assert not is_error(result)
        assert result.value.transferred_contact_hashes == 1

        contacts = asyncio.run(
            container.dedup_repository.list_contact_hashes(TENANT, survivor.id)
        )
        assert len(contacts) == 1

    def test_merge_same_candidate_returns_error(self) -> None:
        container = get_container()
        c = _save_candidate()
        result = asyncio.run(
            container.dedup_use_case.merge_candidates(TENANT, c.id, c.id)
        )
        assert is_error(result)

    def test_merge_nonexistent_survivor_returns_error(self) -> None:
        container = get_container()
        absorbed = _save_candidate()
        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, CandidateId.generate(), absorbed.id
            )
        )
        assert is_error(result)

    def test_merge_nonexistent_absorbed_returns_error(self) -> None:
        container = get_container()
        survivor = _save_candidate()
        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, CandidateId.generate()
            )
        )
        assert is_error(result)

    def test_merge_creates_merge_log(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        assert not is_error(result)
        assert result.value.merge_log.id is not None
        assert result.value.merge_log.status == MergeStatus.MERGED

    def test_double_merge_returns_conflict(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")
        survivor2 = _save_candidate("Выживший 2")

        asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        # absorbed already deleted → NOT_FOUND
        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor2.id, absorbed.id
            )
        )
        assert is_error(result)

    def test_merge_transfers_resume_provenance(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        provenance_id = uuid4()
        absorbed.attach_resume(provenance_id)
        asyncio.run(container.candidate_repository.save(absorbed))

        result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        assert not is_error(result)

        surv = asyncio.run(container.candidate_repository.get(TENANT, survivor.id))
        assert surv is not None
        assert surv.resume_provenance == provenance_id


# ---------------------------------------------------------------------------
# Use cases: JUGO-153 (rollback)
# ---------------------------------------------------------------------------


class TestRollbackMerge:
    def test_rollback_restores_absorbed(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        merge_result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        merge_log_id = str(merge_result.value.merge_log.id)

        result = asyncio.run(
            container.dedup_use_case.rollback_merge(TENANT, merge_log_id)
        )
        assert not is_error(result)
        assert result.value.status == MergeStatus.ROLLED_BACK

        restored = asyncio.run(
            container.candidate_repository.get(TENANT, absorbed.id)
        )
        assert restored is not None
        assert restored.full_name == "Поглощаемый"

    def test_rollback_nonexistent_returns_error(self) -> None:
        container = get_container()
        result = asyncio.run(
            container.dedup_use_case.rollback_merge(TENANT, str(uuid4()))
        )
        assert is_error(result)

    def test_double_rollback_returns_conflict(self) -> None:
        container = get_container()
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")

        merge_result = asyncio.run(
            container.dedup_use_case.merge_candidates(
                TENANT, survivor.id, absorbed.id
            )
        )
        merge_log_id = str(merge_result.value.merge_log.id)

        asyncio.run(container.dedup_use_case.rollback_merge(TENANT, merge_log_id))
        result = asyncio.run(
            container.dedup_use_case.rollback_merge(TENANT, merge_log_id)
        )
        assert is_error(result)


# ---------------------------------------------------------------------------
# Use cases: JUGO-155 (auto-merge)
# ---------------------------------------------------------------------------


class TestAutoMerge:
    def test_auto_merge_disabled_returns_error(self) -> None:
        import os

        container = get_container()
        c = _save_candidate()
        old = os.environ.get("ATS_DEDUP_AUTO_MERGE")
        os.environ["ATS_DEDUP_AUTO_MERGE"] = "0"
        try:
            result = asyncio.run(
                container.dedup_use_case.auto_merge_exact(TENANT, c.id)
            )
            assert is_error(result)
        finally:
            if old is None:
                os.environ.pop("ATS_DEDUP_AUTO_MERGE", None)
            else:
                os.environ["ATS_DEDUP_AUTO_MERGE"] = old

    def test_auto_merge_no_duplicates(self) -> None:
        import os

        container = get_container()
        c = _save_candidate()
        old = os.environ.get("ATS_DEDUP_AUTO_MERGE")
        os.environ["ATS_DEDUP_AUTO_MERGE"] = "1"
        try:
            result = asyncio.run(
                container.dedup_use_case.auto_merge_exact(TENANT, c.id)
            )
            assert not is_error(result)
            assert result.value is None
        finally:
            if old is None:
                os.environ.pop("ATS_DEDUP_AUTO_MERGE", None)
            else:
                os.environ["ATS_DEDUP_AUTO_MERGE"] = old

    def test_auto_merge_with_exact_duplicate(self) -> None:
        import os

        container = get_container()
        c1 = _save_candidate("Иван Иванов")
        c2 = _save_candidate("Иван Иванов Дубль")
        _register_contact(c1, ContactKind.EMAIL, "auto@example.com")
        _register_contact(c2, ContactKind.EMAIL, "auto@example.com")

        old = os.environ.get("ATS_DEDUP_AUTO_MERGE")
        os.environ["ATS_DEDUP_AUTO_MERGE"] = "1"
        try:
            result = asyncio.run(
                container.dedup_use_case.auto_merge_exact(TENANT, c1.id)
            )
            assert not is_error(result)
            assert result.value is not None
            assert result.value.transferred_contact_hashes >= 0
        finally:
            if old is None:
                os.environ.pop("ATS_DEDUP_AUTO_MERGE", None)
            else:
                os.environ["ATS_DEDUP_AUTO_MERGE"] = old


# ---------------------------------------------------------------------------
# API tests (JUGO-150..155)
# ---------------------------------------------------------------------------


class TestRegisterContactAPI:
    def test_register_contact_201(self) -> None:
        c = _save_candidate()
        resp = client.post(
            f"/api/v1/candidates/{c.id.value}/contacts",
            json={"kind": "email", "value": "api@example.com", "is_primary": True},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "registered"
        assert "value_hash" in data

    def test_register_contact_empty_value_400(self) -> None:
        c = _save_candidate()
        resp = client.post(
            f"/api/v1/candidates/{c.id.value}/contacts",
            json={"kind": "email", "value": "  "},
        )
        assert resp.status_code == 400

    def test_register_contact_invalid_kind_400(self) -> None:
        c = _save_candidate()
        resp = client.post(
            f"/api/v1/candidates/{c.id.value}/contacts",
            json={"kind": "invalid_kind", "value": "test@example.com"},
        )
        assert resp.status_code == 400


class TestCheckContactAPI:
    def test_check_existing_contact(self) -> None:
        c = _save_candidate()
        client.post(
            f"/api/v1/candidates/{c.id.value}/contacts",
            json={"kind": "email", "value": "check@example.com"},
        )
        resp = client.get(
            "/api/v1/candidates/contacts/check",
            params={"kind": "email", "value": "check@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        assert str(c.id.value) in data["candidate_ids"]

    def test_check_nonexistent_contact(self) -> None:
        resp = client.get(
            "/api/v1/candidates/contacts/check",
            params={"kind": "email", "value": "nonexistent@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["exists"] is False


class TestFindDuplicatesAPI:
    def test_find_duplicates_for_candidate(self) -> None:
        c1 = _save_candidate("Иван")
        c2 = _save_candidate("Иван Дубль")
        client.post(
            f"/api/v1/candidates/{c1.id.value}/contacts",
            json={"kind": "email", "value": "dup@example.com"},
        )
        client.post(
            f"/api/v1/candidates/{c2.id.value}/contacts",
            json={"kind": "email", "value": "dup@example.com"},
        )
        resp = client.get(f"/api/v1/candidates/{c1.id.value}/duplicates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_find_all_duplicates(self) -> None:
        _save_candidate("Иван Иванов", "Dev born 1990", "Москва")
        _save_candidate("Иван Иванов", "Dev born 1990", "Москва")
        resp = client.get("/api/v1/candidates/duplicates")
        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert "total" in data


class TestMergeAPI:
    def test_merge_two_candidates(self) -> None:
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")
        resp = client.post(
            "/api/v1/candidates/merge",
            json={
                "survivor_id": str(survivor.id.value),
                "absorbed_id": str(absorbed.id.value),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["survivor_id"] == str(survivor.id.value)
        assert data["absorbed_id"] == str(absorbed.id.value)
        assert data["status"] == "merged"
        assert "rollbackable_until" in data

    def test_merge_same_candidate_400(self) -> None:
        c = _save_candidate()
        resp = client.post(
            "/api/v1/candidates/merge",
            json={
                "survivor_id": str(c.id.value),
                "absorbed_id": str(c.id.value),
            },
        )
        assert resp.status_code == 400

    def test_merge_nonexistent_404(self) -> None:
        c = _save_candidate()
        resp = client.post(
            "/api/v1/candidates/merge",
            json={
                "survivor_id": str(c.id.value),
                "absorbed_id": str(uuid4()),
            },
        )
        assert resp.status_code == 404


class TestRollbackAPI:
    def test_rollback_merge(self) -> None:
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")
        merge_resp = client.post(
            "/api/v1/candidates/merge",
            json={
                "survivor_id": str(survivor.id.value),
                "absorbed_id": str(absorbed.id.value),
            },
        )
        merge_log_id = merge_resp.json()["merge_log_id"]

        resp = client.post(f"/api/v1/candidates/merge/{merge_log_id}/rollback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rolled_back"
        assert data["rollbackable"] is False

    def test_rollback_nonexistent_404(self) -> None:
        resp = client.post(f"/api/v1/candidates/merge/{uuid4()}/rollback")
        assert resp.status_code == 404


class TestMergeLogsAPI:
    def test_list_merge_logs(self) -> None:
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")
        client.post(
            "/api/v1/candidates/merge",
            json={
                "survivor_id": str(survivor.id.value),
                "absorbed_id": str(absorbed.id.value),
            },
        )
        resp = client.get(f"/api/v1/candidates/{survivor.id.value}/merge-logs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["status"] == "merged"

    def test_list_merge_logs_empty(self) -> None:
        c = _save_candidate()
        resp = client.get(f"/api/v1/candidates/{c.id.value}/merge-logs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_merge_logs_include_rolled_back(self) -> None:
        survivor = _save_candidate("Выживший")
        absorbed = _save_candidate("Поглощаемый")
        merge_resp = client.post(
            "/api/v1/candidates/merge",
            json={
                "survivor_id": str(survivor.id.value),
                "absorbed_id": str(absorbed.id.value),
            },
        )
        merge_log_id = merge_resp.json()["merge_log_id"]
        client.post(f"/api/v1/candidates/merge/{merge_log_id}/rollback")

        resp = client.get(
            f"/api/v1/candidates/{survivor.id.value}/merge-logs",
            params={"include_rolled_back": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1


class TestAutoMergeAPI:
    def test_auto_merge_disabled_403(self) -> None:
        import os

        c = _save_candidate()
        old = os.environ.get("ATS_DEDUP_AUTO_MERGE")
        os.environ["ATS_DEDUP_AUTO_MERGE"] = "0"
        try:
            resp = client.post(f"/api/v1/candidates/{c.id.value}/auto-merge")
            assert resp.status_code == 403
        finally:
            if old is None:
                os.environ.pop("ATS_DEDUP_AUTO_MERGE", None)
            else:
                os.environ["ATS_DEDUP_AUTO_MERGE"] = old

    def test_auto_merge_no_duplicates(self) -> None:
        import os

        c = _save_candidate()
        old = os.environ.get("ATS_DEDUP_AUTO_MERGE")
        os.environ["ATS_DEDUP_AUTO_MERGE"] = "1"
        try:
            resp = client.post(f"/api/v1/candidates/{c.id.value}/auto-merge")
            assert resp.status_code == 200
            data = resp.json()
            assert data["merged"] is False
            assert data["status"] == "no_duplicates"
        finally:
            if old is None:
                os.environ.pop("ATS_DEDUP_AUTO_MERGE", None)
            else:
                os.environ["ATS_DEDUP_AUTO_MERGE"] = old
