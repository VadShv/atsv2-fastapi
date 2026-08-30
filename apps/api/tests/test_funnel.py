"""Тесты модуля воронки: домен, use cases, REST API (JUGO-130..135)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ats.infra.container_helpers import get_container, reset_container
from ats.main import app
from ats.modules.funnel.application.funnel_use_cases import (
    AddStageInput,
    FunnelPresetUseCase,
    FunnelTransitionUseCase,
    HMDecisionUseCase,
    TransitionInput,
)
from ats.modules.funnel.domain.funnel import (
    AutomationAction,
    AutomationCondition,
    CanonicalPhase,
    FunnelPreset,
    FunnelPresetStatus,
    FunnelSnapshot,
    HMDecision,
    HMDecisionType,
    StageAutomationRule,
    StageCategory,
    StageTransition,
    create_default_preset,
)
from ats.shared.ids import TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

client = TestClient(app)


def setup_function() -> None:
    reset_container()


# ---------------------------------------------------------------------------
# Домен: FunnelPreset + FunnelStage (JUGO-130)
# ---------------------------------------------------------------------------


class TestFunnelPresetAggregate:
    def test_create_publishes_event(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="Custom Pipeline")
        events = preset.collect_events()
        assert preset.status == FunnelPresetStatus.DRAFT
        assert len(events) == 1
        assert events[0].__class__.__name__ == "FunnelPresetCreated"

    def test_add_stage_increments_order_no(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        s1 = preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New", sla_hours=24)
        s2 = preset.add_stage(canonical_phase=CanonicalPhase.SCREENING, name="Screening")
        assert s1.order_no == 0
        assert s2.order_no == 1
        assert s1.is_terminal is False
        assert s2.is_terminal is False

    def test_add_stage_marks_terminal(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        hired = preset.add_stage(canonical_phase=CanonicalPhase.HIRED, name="Hired")
        rejected = preset.add_stage(canonical_phase=CanonicalPhase.REJECTED, name="Rejected")
        assert hired.is_terminal is True
        assert rejected.is_terminal is True
        assert hired.category == StageCategory.INTAKE  # default

    def test_add_stage_rejects_after_publish(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        preset.add_stage(canonical_phase=CanonicalPhase.REJECTED, name="Out")
        preset.publish()
        with pytest.raises(ValueError, match="published"):
            preset.add_stage(canonical_phase=CanonicalPhase.INTERVIEW, name="I")

    def test_publish_requires_terminal_stage(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        with pytest.raises(ValueError, match="terminal"):
            preset.publish()

    def test_publish_empty_preset_fails(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        with pytest.raises(ValueError, match="empty"):
            preset.publish()

    def test_publish_success(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        preset.add_stage(canonical_phase=CanonicalPhase.REJECTED, name="Out")
        preset.publish()
        events = preset.collect_events()
        assert preset.is_published is True
        assert any(e.__class__.__name__ == "FunnelPresetPublished" for e in events)

    def test_archive(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        preset.add_stage(canonical_phase=CanonicalPhase.REJECTED, name="Out")
        preset.publish()
        preset.archive()
        assert preset.status == FunnelPresetStatus.ARCHIVED
        # Idempotent
        preset.archive()
        assert preset.status == FunnelPresetStatus.ARCHIVED

    def test_get_first_stage(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        assert preset.get_first_stage() is None
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        preset.add_stage(canonical_phase=CanonicalPhase.SCREENING, name="Scr")
        first = preset.get_first_stage()
        assert first is not None
        assert first.order_no == 0

    def test_to_snapshot(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        snap = preset.to_snapshot()
        assert snap["name"] == "P1"
        assert len(snap["stages"]) == 1


class TestCreateDefaultPreset:
    def test_default_preset_is_published(self) -> None:
        preset = create_default_preset(TENANT)
        assert preset.is_published is True
        assert preset.name == "Default Pipeline"

    def test_default_preset_has_six_stages(self) -> None:
        preset = create_default_preset(TENANT)
        assert len(preset.stages) == 6
        phases = [s.canonical_phase for s in preset.stages]
        assert CanonicalPhase.NEW in phases
        assert CanonicalPhase.SCREENING in phases
        assert CanonicalPhase.INTERVIEW in phases
        assert CanonicalPhase.OFFER in phases
        assert CanonicalPhase.HIRED in phases
        assert CanonicalPhase.REJECTED in phases

    def test_default_preset_has_terminal_stages(self) -> None:
        preset = create_default_preset(TENANT)
        terminals = [s for s in preset.stages if s.is_terminal]
        assert len(terminals) == 2

    def test_default_preset_order_is_monotonic(self) -> None:
        preset = create_default_preset(TENANT)
        orders = [s.order_no for s in preset.stages]
        assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# Домен: FunnelSnapshot (JUGO-131)
# ---------------------------------------------------------------------------


class TestFunnelSnapshot:
    def _make_preset(self) -> FunnelPreset:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        preset.add_stage(canonical_phase=CanonicalPhase.SCREENING, name="Scr")
        preset.add_stage(canonical_phase=CanonicalPhase.INTERVIEW, name="Int")
        preset.add_stage(canonical_phase=CanonicalPhase.OFFER, name="Off")
        preset.add_stage(canonical_phase=CanonicalPhase.HIRED, name="Hired")
        preset.add_stage(canonical_phase=CanonicalPhase.REJECTED, name="Rej")
        preset.publish()
        return preset

    def test_from_preset_requires_published(self) -> None:
        preset = FunnelPreset.create(tenant_id=TENANT, name="P1")
        preset.add_stage(canonical_phase=CanonicalPhase.NEW, name="New")
        with pytest.raises(ValueError, match="non-published"):
            FunnelSnapshot.from_preset(preset, vacancy_id=uuid4())

    def test_from_preset_copies_stages(self) -> None:
        preset = self._make_preset()
        vacancy = uuid4()
        snap = FunnelSnapshot.from_preset(preset, vacancy_id=vacancy)
        assert snap.vacancy_id == vacancy
        assert snap.preset_id == preset.id
        assert len(snap.stages) == len(preset.stages)

    def test_get_stage_by_canonical(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        screening = snap.get_stage_by_canonical(CanonicalPhase.SCREENING)
        assert screening is not None
        assert screening.name == "Scr"

    def test_get_next_stage(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        first = snap.get_first_stage()
        assert first is not None
        nxt = snap.get_next_stage(first.id)
        assert nxt is not None
        assert nxt.order_no > first.order_no

    def test_get_next_stage_last_returns_none(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        stages = sorted(snap.stages, key=lambda s: s.order_no)
        last = stages[-1]
        assert snap.get_next_stage(last.id) is None

    def test_is_valid_transition_forward(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        stages = sorted(snap.stages, key=lambda s: s.order_no)
        assert snap.is_valid_transition(stages[0].id, stages[1].id) is True
        assert snap.is_valid_transition(stages[1].id, stages[2].id) is True

    def test_is_valid_transition_backward_fails(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        stages = sorted(snap.stages, key=lambda s: s.order_no)
        assert snap.is_valid_transition(stages[2].id, stages[0].id) is False

    def test_is_valid_transition_to_hired_any_nonterminal(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        new_stage = snap.get_stage_by_canonical(CanonicalPhase.NEW)
        hired = snap.get_stage_by_canonical(CanonicalPhase.HIRED)
        assert new_stage is not None and hired is not None
        assert snap.is_valid_transition(new_stage.id, hired.id) is True

    def test_is_valid_transition_to_rejected_any_nonterminal(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        screening = snap.get_stage_by_canonical(CanonicalPhase.SCREENING)
        rejected = snap.get_stage_by_canonical(CanonicalPhase.REJECTED)
        assert screening is not None and rejected is not None
        assert snap.is_valid_transition(screening.id, rejected.id) is True

    def test_is_valid_transition_from_terminal_only_to_new(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        hired = snap.get_stage_by_canonical(CanonicalPhase.HIRED)
        new_stage = snap.get_stage_by_canonical(CanonicalPhase.NEW)
        screening = snap.get_stage_by_canonical(CanonicalPhase.SCREENING)
        assert hired and new_stage and screening
        assert snap.is_valid_transition(hired.id, new_stage.id) is True
        assert snap.is_valid_transition(hired.id, screening.id) is False

    def test_is_valid_transition_noop(self) -> None:
        snap = FunnelSnapshot.from_preset(self._make_preset(), vacancy_id=uuid4())
        first = snap.get_first_stage()
        assert first is not None
        assert snap.is_valid_transition(first.id, first.id) is True


# ---------------------------------------------------------------------------
# Домен: StageTransition (JUGO-132)
# ---------------------------------------------------------------------------


class TestStageTransition:
    def test_to_dict_contains_application_id(self) -> None:
        app_id = uuid4()
        stage_id = uuid4()
        t = StageTransition(
            id=uuid4(),
            application_id=app_id,
            from_stage_id=None,
            to_stage_id=stage_id,
            at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        d = t.to_dict()
        assert d["application_id"] == str(app_id)
        assert d["to_stage_id"] == str(stage_id)
        assert d["from_stage_id"] is None


# ---------------------------------------------------------------------------
# Домен: HMDecision (JUGO-134)
# ---------------------------------------------------------------------------


class TestHMDecision:
    def test_create_approved(self) -> None:
        d = HMDecision.create(
            tenant_id=TENANT,
            application_id=uuid4(),
            stage_id=uuid4(),
            decision=HMDecisionType.APPROVED,
            justification="Strong candidate",
            created_by=uuid4(),
        )
        assert d.decision == HMDecisionType.APPROVED

    def test_create_requires_justification(self) -> None:
        with pytest.raises(ValueError, match="Justification"):
            HMDecision.create(
                tenant_id=TENANT,
                application_id=uuid4(),
                stage_id=uuid4(),
                decision=HMDecisionType.REJECTED,
                justification="  ",
                created_by=uuid4(),
            )


# ---------------------------------------------------------------------------
# Домен: StageAutomationRule (JUGO-135)
# ---------------------------------------------------------------------------


class TestStageAutomationRule:
    def test_create_advance_requires_target(self) -> None:
        with pytest.raises(ValueError, match="target_stage_id"):
            StageAutomationRule.create(
                tenant_id=TENANT,
                stage_id=uuid4(),
                condition=AutomationCondition.SCREENING_SCORE_THRESHOLD,
                action=AutomationAction.ADVANCE,
            )

    def test_create_advance_with_target(self) -> None:
        rule = StageAutomationRule.create(
            tenant_id=TENANT,
            stage_id=uuid4(),
            condition=AutomationCondition.HM_APPROVED,
            action=AutomationAction.ADVANCE,
            target_stage_id=uuid4(),
            params={"threshold": 0.8},
        )
        assert rule.action == AutomationAction.ADVANCE
        assert rule.enabled is True
        assert rule.block_auto_reject is True
        assert rule.params["threshold"] == 0.8

    def test_create_reject_no_target(self) -> None:
        rule = StageAutomationRule.create(
            tenant_id=TENANT,
            stage_id=uuid4(),
            condition=AutomationCondition.SLA_EXPIRED,
            action=AutomationAction.REJECT,
        )
        assert rule.target_stage_id is None


# ---------------------------------------------------------------------------
# Use cases: FunnelPresetUseCase (JUGO-130, JUGO-131)
# ---------------------------------------------------------------------------


class TestFunnelPresetUseCase:
    @pytest.fixture
    def uc(self) -> FunnelPresetUseCase:
        container = get_container()
        return container.funnel_preset_use_case

    @pytest.mark.asyncio
    async def test_create_and_get_preset(self, uc: FunnelPresetUseCase) -> None:
        result = await uc.create_preset(TENANT, "My Pipeline")
        assert not is_error(result)
        preset = result.value
        got = await uc.get_preset(TENANT, preset.id)
        assert not is_error(got)
        assert got.value.name == "My Pipeline"

    @pytest.mark.asyncio
    async def test_create_empty_name_fails(self, uc: FunnelPresetUseCase) -> None:
        result = await uc.create_preset(TENANT, "  ")
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_add_stage_and_publish(self, uc: FunnelPresetUseCase) -> None:
        created = await uc.create_preset(TENANT, "P1")
        preset_id = created.value.id
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.NEW, name="New"),
        )
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.REJECTED, name="Out"),
        )
        pub = await uc.publish_preset(TENANT, preset_id)
        assert not is_error(pub)
        assert pub.value.is_published is True

    @pytest.mark.asyncio
    async def test_publish_without_terminal_fails(self, uc: FunnelPresetUseCase) -> None:
        created = await uc.create_preset(TENANT, "P1")
        preset_id = created.value.id
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.NEW, name="New"),
        )
        result = await uc.publish_preset(TENANT, preset_id)
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_add_stage_to_published_fails(self, uc: FunnelPresetUseCase) -> None:
        created = await uc.create_preset(TENANT, "P1")
        preset_id = created.value.id
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.NEW, name="New"),
        )
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.HIRED, name="Hired"),
        )
        await uc.publish_preset(TENANT, preset_id)
        result = await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.SCREENING, name="Scr"),
        )
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_archive(self, uc: FunnelPresetUseCase) -> None:
        created = await uc.create_preset(TENANT, "P1")
        preset_id = created.value.id
        result = await uc.archive_preset(TENANT, preset_id)
        assert not is_error(result)
        assert result.value.status == FunnelPresetStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_list_presets(self, uc: FunnelPresetUseCase) -> None:
        await uc.create_preset(TENANT, "A")
        await uc.create_preset(TENANT, "B")
        result = await uc.list_presets(TENANT)
        assert not is_error(result)
        assert len(result.value) >= 2

    @pytest.mark.asyncio
    async def test_snapshot_for_vacancy(self, uc: FunnelPresetUseCase) -> None:
        created = await uc.create_preset(TENANT, "P1")
        preset_id = created.value.id
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.NEW, name="New"),
        )
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.HIRED, name="Hired"),
        )
        await uc.publish_preset(TENANT, preset_id)
        vacancy_id = uuid4()
        result = await uc.snapshot_for_vacancy(TENANT, preset_id, vacancy_id)
        assert not is_error(result)
        assert result.value.vacancy_id == vacancy_id
        assert len(result.value.stages) == 2

    @pytest.mark.asyncio
    async def test_snapshot_non_published_fails(self, uc: FunnelPresetUseCase) -> None:
        created = await uc.create_preset(TENANT, "P1")
        preset_id = created.value.id
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.NEW, name="New"),
        )
        await uc.add_stage(
            TENANT,
            preset_id,
            AddStageInput(canonical_phase=CanonicalPhase.HIRED, name="Hired"),
        )
        result = await uc.snapshot_for_vacancy(TENANT, preset_id, uuid4())
        assert is_error(result)


# ---------------------------------------------------------------------------
# Use cases: FunnelTransitionUseCase (JUGO-132)
# ---------------------------------------------------------------------------


class TestFunnelTransitionUseCase:
    @pytest.fixture
    def uc(self) -> FunnelTransitionUseCase:
        container = get_container()
        return container.funnel_transition_use_case

    @pytest.fixture
    def preset_uc(self) -> FunnelPresetUseCase:
        container = get_container()
        return container.funnel_preset_use_case

    @pytest.mark.asyncio
    async def _setup_snapshot(
        self, preset_uc: FunnelPresetUseCase
    ) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
        """Create preset + snapshot, return (vacancy_id, app_id, candidate_id,
        new_id, screening_id, hired_id, rejected_id)."""
        preset = create_default_preset(TENANT)
        await preset_uc._preset_repo.save(preset)
        vacancy_id = uuid4()
        await preset_uc.snapshot_for_vacancy(TENANT, preset.id, vacancy_id)
        snap = await preset_uc._snapshot_repo.get_by_vacancy(TENANT, vacancy_id)
        assert snap is not None
        new_stage = snap.get_stage_by_canonical(CanonicalPhase.NEW)
        screening = snap.get_stage_by_canonical(CanonicalPhase.SCREENING)
        hired = snap.get_stage_by_canonical(CanonicalPhase.HIRED)
        rejected = snap.get_stage_by_canonical(CanonicalPhase.REJECTED)
        assert new_stage and screening and hired and rejected
        return (
            vacancy_id,
            uuid4(),
            uuid4(),
            new_stage.id,
            screening.id,
            hired.id,
            rejected.id,
        )

    @pytest.mark.asyncio
    async def test_transition_forward(
        self, uc: FunnelTransitionUseCase, preset_uc: FunnelPresetUseCase
    ) -> None:
        (
            vacancy_id,
            app_id,
            candidate_id,
            new_id,
            screening_id,
            _,
            _,
        ) = await self._setup_snapshot(preset_uc)
        result = await uc.transition(
            TENANT,
            TransitionInput(
                application_id=app_id,
                vacancy_id=vacancy_id,
                from_stage_id=new_id,
                to_stage_id=screening_id,
                candidate_id=candidate_id,
                reason="Passed initial screening",
            ),
        )
        assert not is_error(result)
        assert result.value.to_stage_id == screening_id

    @pytest.mark.asyncio
    async def test_transition_noop(
        self, uc: FunnelTransitionUseCase, preset_uc: FunnelPresetUseCase
    ) -> None:
        (
            vacancy_id,
            app_id,
            candidate_id,
            new_id,
            _,
            _,
            _,
        ) = await self._setup_snapshot(preset_uc)
        result = await uc.transition(
            TENANT,
            TransitionInput(
                application_id=app_id,
                vacancy_id=vacancy_id,
                from_stage_id=new_id,
                to_stage_id=new_id,
                candidate_id=candidate_id,
            ),
        )
        assert not is_error(result)
        assert result.value.reason == "no-op"

    @pytest.mark.asyncio
    async def test_transition_invalid_backward(
        self, uc: FunnelTransitionUseCase, preset_uc: FunnelPresetUseCase
    ) -> None:
        (
            vacancy_id,
            app_id,
            candidate_id,
            new_id,
            screening_id,
            _,
            _,
        ) = await self._setup_snapshot(preset_uc)
        result = await uc.transition(
            TENANT,
            TransitionInput(
                application_id=app_id,
                vacancy_id=vacancy_id,
                from_stage_id=screening_id,
                to_stage_id=new_id,
                candidate_id=candidate_id,
            ),
        )
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_transition_to_rejected(
        self, uc: FunnelTransitionUseCase, preset_uc: FunnelPresetUseCase
    ) -> None:
        (
            vacancy_id,
            app_id,
            candidate_id,
            new_id,
            _,
            _,
            rejected_id,
        ) = await self._setup_snapshot(preset_uc)
        result = await uc.transition(
            TENANT,
            TransitionInput(
                application_id=app_id,
                vacancy_id=vacancy_id,
                from_stage_id=new_id,
                to_stage_id=rejected_id,
                candidate_id=candidate_id,
                reason="Did not meet requirements",
            ),
        )
        assert not is_error(result)
        assert result.value.to_stage_id == rejected_id

    @pytest.mark.asyncio
    async def test_transition_snapshot_not_found(self, uc: FunnelTransitionUseCase) -> None:
        result = await uc.transition(
            TENANT,
            TransitionInput(
                application_id=uuid4(),
                vacancy_id=uuid4(),
                from_stage_id=None,
                to_stage_id=uuid4(),
                candidate_id=uuid4(),
            ),
        )
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_get_transitions(
        self, uc: FunnelTransitionUseCase, preset_uc: FunnelPresetUseCase
    ) -> None:
        (
            vacancy_id,
            app_id,
            candidate_id,
            new_id,
            screening_id,
            _,
            _,
        ) = await self._setup_snapshot(preset_uc)
        await uc.transition(
            TENANT,
            TransitionInput(
                application_id=app_id,
                vacancy_id=vacancy_id,
                from_stage_id=new_id,
                to_stage_id=screening_id,
                candidate_id=candidate_id,
            ),
        )
        result = await uc.get_transitions(TENANT, app_id)
        assert not is_error(result)
        assert len(result.value) == 1

    @pytest.mark.asyncio
    async def test_get_transitions_isolated_by_application(
        self, uc: FunnelTransitionUseCase, preset_uc: FunnelPresetUseCase
    ) -> None:
        """Verify transitions are filtered by application_id (JUGO-132)."""
        (
            vacancy_id,
            app_id,
            candidate_id,
            new_id,
            screening_id,
            _,
            _,
        ) = await self._setup_snapshot(preset_uc)
        await uc.transition(
            TENANT,
            TransitionInput(
                application_id=app_id,
                vacancy_id=vacancy_id,
                from_stage_id=new_id,
                to_stage_id=screening_id,
                candidate_id=candidate_id,
            ),
        )
        other = await uc.get_transitions(TENANT, uuid4())
        assert not is_error(other)
        assert len(other.value) == 0


# ---------------------------------------------------------------------------
# Use cases: HMDecisionUseCase (JUGO-134)
# ---------------------------------------------------------------------------


class TestHMDecisionUseCase:
    @pytest.fixture
    def uc(self) -> HMDecisionUseCase:
        container = get_container()
        return container.hm_decision_use_case

    @pytest.mark.asyncio
    async def test_record_and_list(self, uc: HMDecisionUseCase) -> None:
        app_id = uuid4()
        stage_id = uuid4()
        result = await uc.record_decision(
            TENANT,
            app_id,
            stage_id,
            HMDecisionType.APPROVED,
            "Excellent fit",
            created_by=uuid4(),
        )
        assert not is_error(result)
        listed = await uc.list_decisions(TENANT, app_id)
        assert not is_error(listed)
        assert len(listed.value) == 1

    @pytest.mark.asyncio
    async def test_record_empty_justification_fails(self, uc: HMDecisionUseCase) -> None:
        result = await uc.record_decision(
            TENANT,
            uuid4(),
            uuid4(),
            HMDecisionType.NEED_INFO,
            "",
            created_by=uuid4(),
        )
        assert is_error(result)

    @pytest.mark.asyncio
    async def test_get_latest_decision(self, uc: HMDecisionUseCase) -> None:
        app_id = uuid4()
        stage_id = uuid4()
        await uc.record_decision(
            TENANT,
            app_id,
            stage_id,
            HMDecisionType.NEED_INFO,
            "Need more info",
            created_by=uuid4(),
        )
        await uc.record_decision(
            TENANT,
            app_id,
            stage_id,
            HMDecisionType.APPROVED,
            "Approved after clarification",
            created_by=uuid4(),
        )
        result = await uc.get_latest_decision(TENANT, app_id, stage_id)
        assert not is_error(result)
        assert result.value is not None
        assert result.value.decision == HMDecisionType.APPROVED


# ---------------------------------------------------------------------------
# REST API (JUGO-130..134)
# ---------------------------------------------------------------------------


class TestFunnelPresetsAPI:
    def test_create_preset(self) -> None:
        resp = client.post("/api/v1/funnel/presets", json={"name": "API Pipeline"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "API Pipeline"
        assert data["status"] == "draft"
        assert data["stages"] == []

    def test_create_preset_validation(self) -> None:
        resp = client.post("/api/v1/funnel/presets", json={"name": ""})
        assert resp.status_code == 422

    def test_list_presets(self) -> None:
        client.post("/api/v1/funnel/presets", json={"name": "A"})
        client.post("/api/v1/funnel/presets", json={"name": "B"})
        resp = client.get("/api/v1/funnel/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    def test_get_preset_not_found(self) -> None:
        resp = client.get(f"/api/v1/funnel/presets/{uuid4()}")
        assert resp.status_code == 404

    def test_add_stage_and_publish(self) -> None:
        created = client.post("/api/v1/funnel/presets", json={"name": "P1"}).json()
        preset_id = created["id"]
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={
                "canonical_phase": "new",
                "name": "New",
                "sla_hours": 24,
            },
        )
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "hired", "name": "Hired"},
        )
        resp = client.post(f"/api/v1/funnel/presets/{preset_id}/publish")
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

    def test_publish_without_terminal(self) -> None:
        created = client.post("/api/v1/funnel/presets", json={"name": "P1"}).json()
        preset_id = created["id"]
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "new", "name": "New"},
        )
        resp = client.post(f"/api/v1/funnel/presets/{preset_id}/publish")
        assert resp.status_code == 400

    def test_archive(self) -> None:
        created = client.post("/api/v1/funnel/presets", json={"name": "P1"}).json()
        preset_id = created["id"]
        resp = client.post(f"/api/v1/funnel/presets/{preset_id}/archive")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"


class TestFunnelSnapshotAPI:
    def test_snapshot_for_vacancy(self) -> None:
        created = client.post("/api/v1/funnel/presets", json={"name": "P1"}).json()
        preset_id = created["id"]
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "new", "name": "New"},
        )
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "hired", "name": "Hired"},
        )
        client.post(f"/api/v1/funnel/presets/{preset_id}/publish")
        vacancy_id = str(uuid4())
        resp = client.post(f"/api/v1/funnel/presets/{preset_id}/snapshot/{vacancy_id}")
        assert resp.status_code == 201
        data = resp.json()
        assert data["vacancy_id"] == vacancy_id
        assert data["stages_count"] == 2

    def test_snapshot_non_published(self) -> None:
        created = client.post("/api/v1/funnel/presets", json={"name": "P1"}).json()
        preset_id = created["id"]
        resp = client.post(f"/api/v1/funnel/presets/{preset_id}/snapshot/{uuid4()}")
        assert resp.status_code == 400


class TestFunnelTransitionsAPI:
    def _setup(self) -> dict:
        created = client.post("/api/v1/funnel/presets", json={"name": "P1"}).json()
        preset_id = created["id"]
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "new", "name": "New"},
        )
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "screening", "name": "Scr"},
        )
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "hired", "name": "Hired"},
        )
        client.post(
            f"/api/v1/funnel/presets/{preset_id}/stages",
            json={"canonical_phase": "rejected", "name": "Rej"},
        )
        client.post(f"/api/v1/funnel/presets/{preset_id}/publish")
        vacancy_id = str(uuid4())
        client.post(f"/api/v1/funnel/presets/{preset_id}/snapshot/{vacancy_id}")
        preset = client.get(f"/api/v1/funnel/presets/{preset_id}").json()
        stages = {s["canonical_phase"]: s["id"] for s in preset["stages"]}
        return {
            "vacancy_id": vacancy_id,
            "new_id": stages["new"],
            "screening_id": stages["screening"],
            "hired_id": stages["hired"],
            "rejected_id": stages["rejected"],
        }

    def test_transition_forward(self) -> None:
        ctx = self._setup()
        app_id = str(uuid4())
        resp = client.post(
            "/api/v1/funnel/transitions",
            json={
                "application_id": app_id,
                "vacancy_id": ctx["vacancy_id"],
                "from_stage_id": ctx["new_id"],
                "to_stage_id": ctx["screening_id"],
                "candidate_id": str(uuid4()),
                "reason": "ok",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["to_stage_id"] == ctx["screening_id"]

    def test_transition_noop(self) -> None:
        ctx = self._setup()
        app_id = str(uuid4())
        resp = client.post(
            "/api/v1/funnel/transitions",
            json={
                "application_id": app_id,
                "vacancy_id": ctx["vacancy_id"],
                "from_stage_id": ctx["new_id"],
                "to_stage_id": ctx["new_id"],
                "candidate_id": str(uuid4()),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["reason"] == "no-op"

    def test_transition_invalid(self) -> None:
        ctx = self._setup()
        resp = client.post(
            "/api/v1/funnel/transitions",
            json={
                "application_id": str(uuid4()),
                "vacancy_id": ctx["vacancy_id"],
                "from_stage_id": ctx["screening_id"],
                "to_stage_id": ctx["new_id"],
                "candidate_id": str(uuid4()),
            },
        )
        assert resp.status_code == 400

    def test_transition_no_snapshot(self) -> None:
        resp = client.post(
            "/api/v1/funnel/transitions",
            json={
                "application_id": str(uuid4()),
                "vacancy_id": str(uuid4()),
                "from_stage_id": None,
                "to_stage_id": str(uuid4()),
                "candidate_id": str(uuid4()),
            },
        )
        assert resp.status_code == 404

    def test_list_transitions(self) -> None:
        ctx = self._setup()
        app_id = str(uuid4())
        client.post(
            "/api/v1/funnel/transitions",
            json={
                "application_id": app_id,
                "vacancy_id": ctx["vacancy_id"],
                "from_stage_id": ctx["new_id"],
                "to_stage_id": ctx["screening_id"],
                "candidate_id": str(uuid4()),
            },
        )
        resp = client.get(f"/api/v1/funnel/transitions/{app_id}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_transitions_empty_for_other(self) -> None:
        ctx = self._setup()
        app_id = str(uuid4())
        client.post(
            "/api/v1/funnel/transitions",
            json={
                "application_id": app_id,
                "vacancy_id": ctx["vacancy_id"],
                "from_stage_id": ctx["new_id"],
                "to_stage_id": ctx["screening_id"],
                "candidate_id": str(uuid4()),
            },
        )
        resp = client.get(f"/api/v1/funnel/transitions/{uuid4()}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestHMDecisionsAPI:
    def test_record_and_list(self) -> None:
        app_id = str(uuid4())
        stage_id = str(uuid4())
        resp = client.post(
            "/api/v1/funnel/hm-decisions",
            json={
                "application_id": app_id,
                "stage_id": stage_id,
                "decision": "approved",
                "justification": "Great candidate",
                "created_by": str(uuid4()),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["decision"] == "approved"
        listed = client.get(f"/api/v1/funnel/hm-decisions/{app_id}")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

    def test_record_validation(self) -> None:
        resp = client.post(
            "/api/v1/funnel/hm-decisions",
            json={
                "application_id": str(uuid4()),
                "stage_id": str(uuid4()),
                "decision": "rejected",
                "justification": "",
                "created_by": str(uuid4()),
            },
        )
        assert resp.status_code == 422

    def test_list_empty(self) -> None:
        resp = client.get(f"/api/v1/funnel/hm-decisions/{uuid4()}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
