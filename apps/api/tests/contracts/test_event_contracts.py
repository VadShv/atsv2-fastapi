"""Контрактные тесты: доменные события валидны по JSON Schema (contracts/events/).

ТЗ §4.3: контракт события версионируется; контрактные тесты фиксируют схемы.
Гарантируют, что событие из кода соответствует зафиксированному контракту.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import validate

from ats.modules.candidates.domain.candidate import (
    CandidateCreated,
    CandidateSource,
    CandidateUpdated,
    ResumeAttached,
)
from ats.modules.candidates.domain.resume import ResumeVersionCreated
from ats.modules.funnel.domain.funnel import (
    FunnelPresetCreated,
    FunnelPresetPublished,
    FunnelTransitionEvent,
    HMDecisionRecorded,
)
from ats.modules.recruitment.domain.application import (
    ApplicationCreated,
    ApplicationRejected,
    ApplicationStage,
    StageChanged,
)
from ats.modules.recruitment.domain.comment import CommentPosted
from ats.modules.recruitment.domain.requirement_set import RequirementSetActivated
from ats.modules.recruitment.domain.vacancy import (
    ScreeningCriteriaGenerated,
    Seniority,
    VacancyClosed,
    VacancyCreated,
    VacancyPublished,
    VacancyStatus,
    VacancyStatusChanged,
)
from ats.shared.events import ActorRef, EventEnvelope

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"


def _load_schema(name: str) -> dict:
    return json.loads((CONTRACTS_DIR / name).read_text())


def _envelope(event) -> dict:
    return EventEnvelope.from_event(event, actor=ActorRef.user("u1")).to_dict()


def _now():
    return datetime.now(UTC)


# --- VacancyCreated ---


def test_vacancy_created_envelope_valid():
    event = VacancyCreated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        title="Backend Developer",
        seniority=Seniority.SENIOR.value,
        team="Platform",
        status=VacancyStatus.DRAFT.value,
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("vacancy.created.v1.schema.json"),
    )
    assert envelope["event_type"] == "vacancy.created"
    assert envelope["schema_version"] == 1


# --- ScreeningCriteriaGenerated ---


def test_screening_criteria_generated_envelope_valid():
    event = ScreeningCriteriaGenerated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        provenance_id=uuid4(),
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("vacancy.screening.generated.v1.schema.json"),
    )
    assert envelope["event_type"] == "vacancy.screening.generated"
    assert envelope["aggregate"]["type"] == "vacancy"


# --- VacancyPublished ---


def test_vacancy_published_envelope_valid():
    event = VacancyPublished(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        title="Backend Developer",
        team="Platform",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("vacancy.published.v1.schema.json"),
    )
    assert envelope["event_type"] == "vacancy.published"


# --- VacancyClosed ---


def test_vacancy_closed_envelope_valid():
    event = VacancyClosed(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        hired_count=3,
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("vacancy.closed.v1.schema.json"),
    )
    assert envelope["event_type"] == "vacancy.closed"


# --- VacancyStatusChanged ---


def test_vacancy_status_changed_envelope_valid():
    event = VacancyStatusChanged(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        from_status="draft",
        to_status="open",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("vacancy.status.changed.v1.schema.json"),
    )
    assert envelope["event_type"] == "vacancy.status.changed"


# --- RequirementSetActivated ---


def test_requirement_set_activated_envelope_valid():
    event = RequirementSetActivated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        vacancy_id=uuid4(),
        requirement_set_id=uuid4(),
        version_number=2,
        origin="ai",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("vacancy.requirements.activated.v1.schema.json"),
    )
    assert envelope["event_type"] == "vacancy.requirements.activated"


# --- CandidateCreated ---


def test_candidate_created_envelope_valid():
    event = CandidateCreated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        candidate_id=uuid4(),
        full_name="Иван Иванов",
        source=CandidateSource.REFERRAL.value,
        resume_provenance_id=None,
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("candidate.created.v1.schema.json"),
    )
    assert envelope["event_type"] == "candidate.created"


# --- CandidateUpdated ---


def test_candidate_updated_envelope_valid():
    event = CandidateUpdated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        candidate_id=uuid4(),
        full_name="Иван Петров",
        fields_changed=("full_name", "phone"),
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("candidate.updated.v1.schema.json"),
    )
    assert envelope["event_type"] == "candidate.updated"


# --- ResumeAttached ---


def test_resume_attached_envelope_valid():
    event = ResumeAttached(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        candidate_id=uuid4(),
        resume_provenance_id="prov-123",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("candidate.resume.attached.v1.schema.json"),
    )
    assert envelope["event_type"] == "candidate.resume.attached"


# --- ResumeVersionCreated ---


def test_resume_version_created_envelope_valid():
    event = ResumeVersionCreated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        candidate_id=uuid4(),
        version_number=1,
        content_hash="abc123",
        source_kind="upload",
        file_type="pdf",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("resume.version.created.v1.schema.json"),
    )
    assert envelope["event_type"] == "resume.version.created"


# --- ApplicationCreated ---


def test_application_created_envelope_valid():
    event = ApplicationCreated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        application_id=uuid4(),
        candidate_id=uuid4(),
        vacancy_id=uuid4(),
        stage=ApplicationStage.NEW.value,
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("application.created.v1.schema.json"),
    )


# --- StageChanged ---


def test_stage_changed_envelope_valid():
    event = StageChanged(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        application_id=uuid4(),
        from_stage_id=ApplicationStage.NEW.value,
        to_stage_id=ApplicationStage.SCREENING.value,
        candidate_id=uuid4(),
        vacancy_id=uuid4(),
        reason="Passed initial check",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("application.stage.changed.v1.schema.json"),
    )
    assert envelope["payload"]["from_stage_id"] == "new"
    assert envelope["payload"]["to_stage_id"] == "screening"


# --- ApplicationRejected ---


def test_application_rejected_envelope_valid():
    event = ApplicationRejected(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        application_id=uuid4(),
        candidate_id=uuid4(),
        vacancy_id=uuid4(),
        reason_code="no_fit",
        reason_label="Not a fit for the role",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("application.rejected.v1.schema.json"),
    )
    assert envelope["event_type"] == "application.rejected"


# --- CommentPosted ---


def test_comment_posted_envelope_valid():
    event = CommentPosted(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        thread_id=uuid4(),
        comment_id=uuid4(),
        application_id=uuid4(),
        author_id="u1",
        is_private=False,
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("application.comment.posted.v1.schema.json"),
    )
    assert envelope["event_type"] == "application.comment.posted"


# --- FunnelPresetCreated ---


def test_funnel_preset_created_envelope_valid():
    event = FunnelPresetCreated(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        preset_id=uuid4(),
        name="Standard Hiring",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("funnel.preset.created.v1.schema.json"),
    )
    assert envelope["event_type"] == "funnel.preset.created"


# --- FunnelPresetPublished ---


def test_funnel_preset_published_envelope_valid():
    event = FunnelPresetPublished(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        preset_id=uuid4(),
        name="Standard Hiring",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("funnel.preset.published.v1.schema.json"),
    )
    assert envelope["event_type"] == "funnel.preset.published"


# --- FunnelTransitionEvent ---


def test_funnel_transition_envelope_valid():
    event = FunnelTransitionEvent(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        application_id=uuid4(),
        from_stage_id=None,
        to_stage_id="stage-2",
        vacancy_id=uuid4(),
        candidate_id=uuid4(),
        reason="Initial placement",
        actor_type="user",
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("application.funnel.transition.v1.schema.json"),
    )
    assert envelope["event_type"] == "application.funnel.transition"


# --- HMDecisionRecorded ---


def test_hm_decision_envelope_valid():
    event = HMDecisionRecorded(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
        application_id=uuid4(),
        decision="approved",
        stage_id=uuid4(),
    )
    envelope = _envelope(event)
    validate(instance=envelope, schema=_load_schema("envelope.schema.json"))
    validate(
        instance=envelope["payload"],
        schema=_load_schema("application.hm.decision.v1.schema.json"),
    )
    assert envelope["event_type"] == "application.hm.decision"


# --- Реестр ---


def test_event_registry_lists_all_known_events():
    registry = json.loads((CONTRACTS_DIR / "registry.v1.json").read_text())
    expected = {
        "vacancy.created",
        "vacancy.published",
        "vacancy.closed",
        "vacancy.status.changed",
        "vacancy.requirements.activated",
        "vacancy.screening.generated",
        "candidate.created",
        "candidate.updated",
        "candidate.resume.attached",
        "resume.version.created",
        "application.created",
        "application.stage.changed",
        "application.rejected",
        "application.comment.posted",
        "application.funnel.transition",
        "application.hm.decision",
        "funnel.preset.created",
        "funnel.preset.published",
        "ai.run.completed",
        "ai.run.failed",
    }
    assert set(registry["events"].keys()) == expected


def test_unknown_event_type_raises():
    """Доменное событие без регистрации в контракте → явная ошибка (whitebox)."""
    from ats.shared.events import DomainEvent

    class UnregisteredEvent(DomainEvent):
        pass

    event = UnregisteredEvent(
        event_id=uuid4(),
        occurred_at=_now(),
        tenant_id=uuid4(),
        payload={},
    )
    with pytest.raises(ValueError, match="не зарегистрировано"):
        EventEnvelope.from_event(event)
