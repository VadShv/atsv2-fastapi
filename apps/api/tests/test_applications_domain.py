"""Тесты домена Application: origin, reject, risk, повторные отклики (JUGO-140..142)."""

from __future__ import annotations

from uuid import uuid4

from ats.modules.recruitment.domain.application import (
    ALLOWED_TRANSITIONS,
    Application,
    ApplicationOrigin,
    ApplicationStage,
    RiskLevel,
)

TENANT_RAW = "00000000-0000-0000-0000-000000000001"


def _make_application(
    origin: ApplicationOrigin = ApplicationOrigin.INCOMING,
    resume_id=None,
) -> Application:
    from ats.shared.ids import CandidateId, TenantId, VacancyId

    return Application.create(
        tenant_id=TenantId.from_string(TENANT_RAW),
        candidate_id=CandidateId(uuid4()),
        vacancy_id=VacancyId(uuid4()),
        origin=origin,
        resume_id=resume_id,
    )


class TestApplicationCreate:
    def test_create_with_default_origin(self) -> None:
        app = _make_application()
        assert app.origin == ApplicationOrigin.INCOMING
        assert app.stage == ApplicationStage.NEW
        assert app.resume_id is None

    def test_create_with_cold_sourcing_origin(self) -> None:
        app = _make_application(origin=ApplicationOrigin.COLD_SOURCING)
        assert app.origin == ApplicationOrigin.COLD_SOURCING

    def test_create_with_resume_id(self) -> None:
        rid = uuid4()
        app = _make_application(resume_id=rid)
        assert app.resume_id == rid

    def test_create_publishes_application_created_event(self) -> None:
        app = _make_application()
        events = app.collect_events()
        assert len(events) == 1
        assert type(events[0]).__name__ == "ApplicationCreated"

    def test_create_sets_stage_entered_at(self) -> None:
        app = _make_application()
        assert app.stage_entered_at is not None


class TestApplicationReject:
    def test_reject_sets_reason_fields(self) -> None:
        app = _make_application()
        app.reject(
            reason_code="skills_mismatch",
            reason_label="Несоответствие навыков",
            internal_note="Не знает FastAPI",
        )
        assert app.is_rejected
        assert app.rejection_reason_code == "skills_mismatch"
        assert app.rejection_reason_label == "Несоответствие навыков"
        assert app.internal_rejection_note == "Не знает FastAPI"

    def test_reject_publishes_application_rejected_event(self) -> None:
        app = _make_application()
        app.reject(reason_code="no_show", reason_label="Неявка")
        events = app.collect_events()
        event_types = [type(e).__name__ for e in events]
        assert "ApplicationRejected" in event_types

    def test_reject_idempotent(self) -> None:
        app = _make_application()
        app.reject(reason_code="r1", reason_label="Reason 1")
        events_after_first = app.collect_events()
        app.reject(reason_code="r2", reason_label="Reason 2")
        events_after_second = app.collect_events()
        # Идемпотентность: второй reject не должен публиковать новое событие
        assert len(events_after_second) == 0

    def test_reject_empty_reason_code_raises(self) -> None:
        app = _make_application()
        try:
            app.reject(reason_code="", reason_label="x")
            assert False, "Should raise"
        except ValueError:
            pass

    def test_reject_sets_risk_level_none_by_default(self) -> None:
        app = _make_application()
        assert app.risk_level == RiskLevel.NONE


class TestApplicationRiskLevel:
    def test_set_risk_level(self) -> None:
        app = _make_application()
        app.set_risk_level(RiskLevel.HIGH)
        assert app.risk_level == RiskLevel.HIGH

    def test_set_risk_level_medium(self) -> None:
        app = _make_application()
        app.set_risk_level(RiskLevel.MEDIUM)
        assert app.risk_level == RiskLevel.MEDIUM


class TestApplicationScreeningScore:
    def test_set_score_updates_screening_score(self) -> None:
        app = _make_application()
        provenance = uuid4()
        app.set_score(0.85, provenance)
        assert app.score == 0.85
        assert app.screening_score == 0.85
        assert app.score_provenance == provenance


class TestApplicationMoveTo:
    def test_move_to_updates_stage_entered_at(self) -> None:
        app = _make_application()
        old_entered = app.stage_entered_at
        app.move_to(ApplicationStage.SCREENING, reason="ok")
        assert app.stage_entered_at >= old_entered

    def test_move_from_rejected_clears_rejection_fields(self) -> None:
        app = _make_application()
        app.reject(reason_code="r1", reason_label="Reason 1")
        assert app.rejection_reason_code is not None
        # REJECTED -> NEW разрешён
        app.move_to(ApplicationStage.NEW)
        assert app.rejection_reason_code is None
        assert app.rejection_reason_label is None
        assert app.internal_rejection_note is None

    def test_allowed_transitions_from_new(self) -> None:
        allowed = ALLOWED_TRANSITIONS[ApplicationStage.NEW]
        assert ApplicationStage.SCREENING in allowed
        assert ApplicationStage.REJECTED in allowed
        assert ApplicationStage.HIRED not in allowed


class TestApplicationStates:
    def test_is_active_when_new(self) -> None:
        app = _make_application()
        assert app.is_active is True

    def test_is_active_false_when_hired(self) -> None:
        app = _make_application()
        app.move_to(ApplicationStage.SCREENING)
        app.move_to(ApplicationStage.INTERVIEW)
        app.move_to(ApplicationStage.OFFER)
        app.move_to(ApplicationStage.HIRED)
        assert app.is_active is False
        assert app.is_terminal is True

    def test_is_active_false_when_rejected(self) -> None:
        app = _make_application()
        app.reject(reason_code="r", reason_label="R")
        assert app.is_active is False
        assert app.is_rejected is True
