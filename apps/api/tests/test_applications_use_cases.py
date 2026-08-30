"""Тесты use cases: create application, reject, timeline, repeat rules (JUGO-140..144)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from ats.infra.container_helpers import get_container, reset_container
from ats.modules.candidates.domain.candidate import Candidate, CandidateSource
from ats.modules.recruitment.application.create_application import CreateApplicationUseCase
from ats.modules.recruitment.application.reject_application import (
    RejectApplicationInput,
    RejectApplicationUseCase,
)
from ats.modules.recruitment.domain.application import ApplicationOrigin, ApplicationStage
from ats.shared.ids import CandidateId, IdempotencyKey, TenantId, VacancyId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def setup_function() -> None:
    reset_container()


def _create_candidate(name: str = "Тест Тестов") -> Candidate:
    container = get_container()
    candidate = Candidate.create(
        tenant_id=TENANT,
        full_name=name,
        source=CandidateSource.DATABASE,
        headline="Developer",
        skills=["Python"],
    )
    asyncio.run(container.candidate_repository.save(candidate))
    return candidate


def _create_vacancy() -> str:
    from fastapi.testclient import TestClient

    from ats.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/v1/vacancies",
        json={
            "title": "Test Dev",
            "seniority": "middle",
            "team": "X",
            "description": "desc",
        },
    )
    return resp.json()["vacancy_id"]


class TestCreateApplicationUseCase:
    def test_create_with_origin_and_resume(self) -> None:
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()
        resume_id = uuid4()

        use_case = CreateApplicationUseCase(container.application_repository)
        result = asyncio.run(
            use_case.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-1"),
                origin=ApplicationOrigin.COLD_SOURCING,
                resume_id=resume_id,
            )
        )
        assert not is_error(result)
        app = result.value
        assert app.origin == ApplicationOrigin.COLD_SOURCING
        assert app.resume_id == resume_id

    def test_repeat_application_active_returns_conflict(self) -> None:
        """JUGO-142: активная заявка → CONFLICT."""
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()

        use_case = CreateApplicationUseCase(container.application_repository)
        # Первая заявка
        asyncio.run(
            use_case.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-2"),
            )
        )
        # Вторая — активная → CONFLICT
        result = asyncio.run(
            use_case.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-3"),
            )
        )
        assert is_error(result)
        assert result.error.code.value == "conflict"

    def test_repeat_application_after_rejection_allowed(self) -> None:
        """JUGO-142: терминальная заявка → новый отклик разрешён."""
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()

        create_uc = CreateApplicationUseCase(container.application_repository)
        reject_uc = RejectApplicationUseCase(container.application_repository)

        # Создаём и отклоняем
        result1 = asyncio.run(
            create_uc.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-4"),
            )
        )
        app = result1.value
        asyncio.run(
            reject_uc.execute(
                tenant_id=TENANT,
                input_dto=RejectApplicationInput(
                    application_id=app.id,
                    reason_code="skills_mismatch",
                    reason_label="Не подходит",
                ),
            )
        )

        # Повторная заявка — разрешена
        result2 = asyncio.run(
            create_uc.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-5"),
            )
        )
        assert not is_error(result2)
        assert result2.value.id != app.id


class TestRejectApplicationUseCase:
    def test_reject_nonexistent_returns_404(self) -> None:
        container = get_container()
        reject_uc = RejectApplicationUseCase(container.application_repository)
        result = asyncio.run(
            reject_uc.execute(
                tenant_id=TENANT,
                input_dto=RejectApplicationInput(
                    application_id=uuid4(),
                    reason_code="r",
                    reason_label="R",
                ),
            )
        )
        assert is_error(result)
        assert result.error.code.value == "not_found"

    def test_reject_empty_reason_code_returns_validation(self) -> None:
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()
        create_uc = CreateApplicationUseCase(container.application_repository)
        app = asyncio.run(
            create_uc.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-6"),
            )
        ).value

        reject_uc = RejectApplicationUseCase(container.application_repository)
        result = asyncio.run(
            reject_uc.execute(
                tenant_id=TENANT,
                input_dto=RejectApplicationInput(
                    application_id=app.id,
                    reason_code="",
                    reason_label="R",
                ),
            )
        )
        assert is_error(result)
        assert result.error.code.value == "validation"

    def test_reject_with_internal_note(self) -> None:
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()
        create_uc = CreateApplicationUseCase(container.application_repository)
        app = asyncio.run(
            create_uc.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-7"),
            )
        ).value

        reject_uc = RejectApplicationUseCase(container.application_repository)
        result = asyncio.run(
            reject_uc.execute(
                tenant_id=TENANT,
                input_dto=RejectApplicationInput(
                    application_id=app.id,
                    reason_code="culture_fit",
                    reason_label="Не подходит по культуре",
                    internal_note="Скрытая причина: уровень завышен",
                ),
            )
        )
        assert not is_error(result)
        assert result.value.rejection_reason_code == "culture_fit"
        assert result.value.internal_rejection_note == "Скрытая причина: уровень завышен"


class TestApplicationTimelineUseCase:
    def test_timeline_for_nonexistent_returns_404(self) -> None:
        container = get_container()
        result = asyncio.run(
            container.application_timeline.execute(
                tenant_id=TENANT,
                application_id=uuid4(),
            )
        )
        assert is_error(result)
        assert result.error.code.value == "not_found"

    def test_timeline_includes_created_and_transitions(self) -> None:
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()

        app = asyncio.run(
            container.create_application.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-tl-1"),
            )
        ).value

        # Переход
        asyncio.run(
            container.move_application.execute(
                tenant_id=TENANT,
                input_dto=type(
                    "DTO",
                    (),
                    {
                        "application_id": app.id,
                        "to_stage": ApplicationStage.SCREENING,
                        "reason": "ok",
                        "ai_provenance": None,
                    },
                )(),
            )
        )

        result = asyncio.run(
            container.application_timeline.execute(tenant_id=TENANT, application_id=app.id)
        )
        assert not is_error(result)
        timeline = result.value
        event_types = [e.event_type for e in timeline.entries]
        assert "created" in event_types
        assert "transition" in event_types

    def test_timeline_includes_rejection(self) -> None:
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()

        app = asyncio.run(
            container.create_application.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-tl-2"),
            )
        ).value

        asyncio.run(
            container.reject_application.execute(
                tenant_id=TENANT,
                input_dto=RejectApplicationInput(
                    application_id=app.id,
                    reason_code="no_fit",
                    reason_label="Не подходит",
                ),
            )
        )

        result = asyncio.run(
            container.application_timeline.execute(tenant_id=TENANT, application_id=app.id)
        )
        timeline = result.value
        event_types = [e.event_type for e in timeline.entries]
        assert "rejection" in event_types

    def test_timeline_sorted_chronologically(self) -> None:
        container = get_container()
        candidate = _create_candidate()
        vacancy_id = _create_vacancy()

        app = asyncio.run(
            container.create_application.execute(
                tenant_id=TENANT,
                candidate_id=CandidateId(candidate.id.value),
                vacancy_id=VacancyId(vacancy_id),
                idempotency_key=IdempotencyKey("test-tl-3"),
            )
        ).value

        result = asyncio.run(
            container.application_timeline.execute(tenant_id=TENANT, application_id=app.id)
        )
        timeline = result.value
        timestamps = [e.timestamp for e in timeline.sorted_entries]
        assert timestamps == sorted(timestamps)
