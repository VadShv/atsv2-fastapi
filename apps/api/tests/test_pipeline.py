"""Тесты пайплайна кандидатов: заявки, переходы по стадиям (как Huntflow)."""

from __future__ import annotations

import pytest

from ats.infra.container import build_container
from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
from ats.modules.recruitment.application.move_application import (
    MoveApplicationInput,
)
from ats.modules.recruitment.domain.application import (
    ALLOWED_TRANSITIONS,
    Application,
    ApplicationStage,
    InvalidTransitionError,
)
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, VacancyId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


class TestApplicationAggregate:
    def test_create_starts_in_new(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        assert app.stage == ApplicationStage.NEW
        events = app.collect_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "ApplicationCreated"

    def test_valid_transition_records_history(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        app.collect_events()

        app.move_to(ApplicationStage.SCREENING, reason="passed initial check")
        assert app.stage == ApplicationStage.SCREENING
        assert len(app.transitions) == 1
        assert app.transitions[0].from_stage == ApplicationStage.NEW
        events = app.collect_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "StageChanged"

    def test_invalid_transition_raises(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        # NEW → INTERVIEW недопустимо (надо через SCREENING)
        with pytest.raises(InvalidTransitionError):
            app.move_to(ApplicationStage.INTERVIEW)

    def test_idempotent_same_stage(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        app.move_to(ApplicationStage.NEW)  # уже NEW
        assert len(app.transitions) == 0

    def test_full_happy_path(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        app.move_to(ApplicationStage.SCREENING)
        app.move_to(ApplicationStage.INTERVIEW)
        app.move_to(ApplicationStage.OFFER)
        app.move_to(ApplicationStage.HIRED)
        assert app.stage == ApplicationStage.HIRED
        assert app.is_terminal
        assert len(app.transitions) == 4

    def test_rejection_allowed_from_any_active_stage(self) -> None:
        for stage in [
            ApplicationStage.NEW,
            ApplicationStage.SCREENING,
            ApplicationStage.INTERVIEW,
            ApplicationStage.OFFER,
        ]:
            assert ApplicationStage.REJECTED in ALLOWED_TRANSITIONS[stage]

    def test_can_return_from_rejected_to_new(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        app.move_to(ApplicationStage.REJECTED)
        app.move_to(ApplicationStage.NEW)
        assert app.stage == ApplicationStage.NEW

    def test_cannot_leave_hired(self) -> None:
        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        app.move_to(ApplicationStage.SCREENING)
        app.move_to(ApplicationStage.INTERVIEW)
        app.move_to(ApplicationStage.OFFER)
        app.move_to(ApplicationStage.HIRED)
        with pytest.raises(InvalidTransitionError):
            app.move_to(ApplicationStage.INTERVIEW)

    def test_set_score_links_provenance(self) -> None:
        from uuid import uuid4

        app = Application.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            vacancy_id=VacancyId.generate(),
        )
        prov = uuid4()
        app.set_score(0.87, prov)
        assert app.score == 0.87
        assert app.score_provenance == prov


class TestMoveApplicationUseCase:
    @pytest.mark.asyncio
    async def test_move_and_persist(self) -> None:
        container = build_container()
        candidate = Candidate.create(
            tenant_id=TENANT,
            full_name="Иван Иванов",
            source=CandidateSource.DATABASE,
        )
        await container.candidate_repository.save(candidate)
        app_result = await container.create_application.execute(
            TENANT, candidate.id, VacancyId.generate(), IdempotencyKey("k1")
        )
        app = app_result.value

        result = await container.move_application.execute(
            TENANT,
            MoveApplicationInput(
                application_id=app.id,
                to_stage=ApplicationStage.SCREENING,
                reason="resume looks good",
            ),
        )
        assert not result.value.is_terminal
        assert result.value.stage == ApplicationStage.SCREENING

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_conflict(self) -> None:
        container = build_container()
        app_result = await container.create_application.execute(
            TENANT,
            CandidateId.generate(),
            VacancyId.generate(),
            IdempotencyKey("k2"),
        )
        app = app_result.value
        result = await container.move_application.execute(
            TENANT,
            MoveApplicationInput(
                application_id=app.id,
                to_stage=ApplicationStage.INTERVIEW,  # недопустимо из NEW
            ),
        )
        assert is_error(result)
        assert result.error.code.value == "conflict"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        from uuid import uuid4

        container = build_container()
        result = await container.move_application.execute(
            TENANT,
            MoveApplicationInput(
                application_id=uuid4(),
                to_stage=ApplicationStage.SCREENING,
            ),
        )
        assert is_error(result)
        assert result.error.code.value == "not_found"

    @pytest.mark.asyncio
    async def test_create_application_idempotent(self) -> None:
        """JUGO-142: повторный активный отклик → CONFLICT."""
        container = build_container()
        candidate = Candidate.create(
            tenant_id=TENANT,
            full_name="Петр Петров",
            source=CandidateSource.REFERRAL,
        )
        await container.candidate_repository.save(candidate)
        vid = VacancyId.generate()

        r1 = await container.create_application.execute(
            TENANT, candidate.id, vid, IdempotencyKey("k3")
        )
        r2 = await container.create_application.execute(
            TENANT, candidate.id, vid, IdempotencyKey("k4")
        )
        assert not is_error(r1)
        # JUGO-142: повторный активный отклик → CONFLICT
        assert is_error(r2)
        assert r2.error.code.value == "conflict"
