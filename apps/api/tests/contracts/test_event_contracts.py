"""Контрактные тесты: доменные события валидны по JSON Schema (contracts/events/).

ТЗ §4.3: контракт события версионируется; контрактные тесты фиксируют схемы.
Гарантируют, что событие из кода соответствует зафиксированному контракту.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import validate

from ats.modules.candidates.domain.candidate import (
    CandidateCreated,
    CandidateSource,
)
from ats.modules.recruitment.domain.application import (
    ApplicationCreated,
    ApplicationStage,
    StageChanged,
)
from ats.modules.recruitment.domain.vacancy import (
    ScreeningCriteriaGenerated,
    Seniority,
    VacancyCreated,
    VacancyStatus,
)
from ats.shared.events import ActorRef, EventEnvelope

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"


def _load_schema(name: str) -> dict:
    return json.loads((CONTRACTS_DIR / name).read_text())


def _envelope(event) -> dict:
    return EventEnvelope.from_event(event, actor=ActorRef.user("u1")).to_dict()


def _now():
    return datetime.now(timezone.utc)


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


# --- Реестр ---

def test_event_registry_lists_all_known_events():
    registry = json.loads((CONTRACTS_DIR / "registry.v1.json").read_text())
    expected = {
        "vacancy.created",
        "vacancy.screening.generated",
        "candidate.created",
        "application.created",
        "application.stage.changed",
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
