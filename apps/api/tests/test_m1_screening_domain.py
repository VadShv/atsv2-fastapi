"""Тесты E-40: M1 Screening — домен (level0 rules, scoring, aggregate).

Чистые функции скоринга + агрегат ScreeningResult.
Без LLM — детерминированная логика.
"""

from __future__ import annotations

from uuid import uuid4

from ats.modules.m1_screening.domain.level0_rules import (
    HARD_DISQUALIFY_REASONS,
    Level0Input,
    check_hard_disqualify,
    check_spam,
    check_unreadable,
    run_level0,
)
from ats.modules.m1_screening.domain.screening import (
    CriterionEvaluation,
    Level0Result,
    OverrideAction,
    ScreeningRecommendation,
    ScreeningResult,
    ScreeningStatus,
    THRESHOLD_AUTO_ADVANCE,
    THRESHOLD_AUTO_REJECT,
    _compute_total_score,
    _derive_recommendation,
)
from ats.shared.ids import (
    ApplicationId,
    CandidateId,
    ProvenanceId,
    ScreeningResultId,
    TenantId,
    VacancyId,
)

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


def _make_ids():
    return (
        ApplicationId(uuid4()),
        CandidateId(uuid4()),
        VacancyId(uuid4()),
    )


# ---------------------------------------------------------------------------
# Level 0: детерминированные правила очистки
# ---------------------------------------------------------------------------


class TestCheckUnreadable:
    def test_short_text_is_unreadable(self) -> None:
        assert check_unreadable("short")

    def test_long_text_is_readable(self) -> None:
        assert not check_unreadable("x" * 100)

    def test_empty_text_is_unreadable(self) -> None:
        assert check_unreadable("")

    def test_whitespace_only_is_unreadable(self) -> None:
        assert check_unreadable("   ")


class TestCheckSpam:
    def test_normal_text_not_spam(self) -> None:
        is_spam, rules = check_spam("Python developer with 5 years experience in FastAPI")
        assert not is_spam
        assert rules == []

    def test_many_urls_is_spam(self) -> None:
        text = " ".join(["http://spam.com"] * 6)
        is_spam, rules = check_spam(text)
        assert is_spam
        assert "too_many_urls" in rules

    def test_excessive_caps_is_spam(self) -> None:
        text = "THISISAREALLYLONGCAPITALIZEDSTRINGTHATTRIGGERSSPAM"
        is_spam, rules = check_spam(text)
        assert is_spam
        assert "excessive_caps" in rules


class TestCheckHardDisqualify:
    def test_known_reasons_match(self) -> None:
        result = check_hard_disqualify(["underage", "blacklisted"])
        assert "underage" in result
        assert "blacklisted" in result

    def test_unknown_reasons_dont_match(self) -> None:
        result = check_hard_disqualify(["some_random_reason"])
        assert result == []

    def test_none_returns_empty(self) -> None:
        assert check_hard_disqualify(None) == []


class TestRunLevel0:
    def test_blacklisted_rejected(self) -> None:
        result = run_level0(Level0Input(resume_text="x" * 100, is_blacklisted=True))
        assert result.rejected
        assert result.reason == "blacklisted"

    def test_hard_disqualify_rejected(self) -> None:
        result = run_level0(
            Level0Input(resume_text="x" * 100, hard_disqualify_reasons=["no_work_permit"])
        )
        assert result.rejected
        assert "hard_disqualify" in result.reason

    def test_duplicate_rejected(self) -> None:
        result = run_level0(Level0Input(resume_text="x" * 100, is_duplicate=True))
        assert result.rejected
        assert result.reason == "duplicate"

    def test_unreadable_rejected(self) -> None:
        result = run_level0(Level0Input(resume_text="short"))
        assert result.rejected
        assert result.reason == "unreadable"

    def test_spam_rejected(self) -> None:
        text = " ".join(["http://spam.com"] * 6)
        result = run_level0(Level0Input(resume_text=text))
        assert result.rejected
        assert result.reason == "spam"

    def test_clean_candidate_passes(self) -> None:
        result = run_level0(
            Level0Input(resume_text="Python developer with 5 years experience in FastAPI")
        )
        assert not result.rejected
        assert result.reason == ""

    def test_blacklisted_takes_priority_over_unreadable(self) -> None:
        result = run_level0(Level0Input(resume_text="x", is_blacklisted=True))
        assert result.rejected
        assert result.reason == "blacklisted"

    def test_hard_disqualify_takes_priority_over_duplicate(self) -> None:
        result = run_level0(
            Level0Input(
                resume_text="x" * 100,
                is_duplicate=True,
                hard_disqualify_reasons=["underage"],
            )
        )
        assert result.rejected
        assert "hard_disqualify" in result.reason


# ---------------------------------------------------------------------------
# Scoring: чистые функции
# ---------------------------------------------------------------------------


def _ev(name: str, score: float, weight: float, must_have: bool = False) -> CriterionEvaluation:
    return CriterionEvaluation(
        criterion_name=name,
        category="hard_skill",
        score=score,
        weight=weight,
        must_have=must_have,
    )


class TestComputeTotalScore:
    def test_all_pass(self) -> None:
        evals = [_ev("a", 1.0, 50), _ev("b", 1.0, 50)]
        assert _compute_total_score(evals) == 1.0

    def test_all_fail(self) -> None:
        evals = [_ev("a", 0.0, 50), _ev("b", 0.0, 50)]
        assert _compute_total_score(evals) == 0.0

    def test_half_scores(self) -> None:
        evals = [_ev("a", 1.0, 50), _ev("b", 0.0, 50)]
        assert _compute_total_score(evals) == 0.5

    def test_must_have_fail_zeros_score(self) -> None:
        evals = [_ev("a", 1.0, 50), _ev("b", 0.0, 50, must_have=True)]
        assert _compute_total_score(evals) == 0.0

    def test_must_have_pass_doesnt_zero(self) -> None:
        evals = [_ev("a", 1.0, 50, must_have=True), _ev("b", 0.0, 50)]
        assert _compute_total_score(evals) == 0.5

    def test_empty_evaluations(self) -> None:
        assert _compute_total_score([]) == 0.0

    def test_weighted_by_weight(self) -> None:
        evals = [_ev("a", 1.0, 80), _ev("b", 0.0, 20)]
        assert _compute_total_score(evals) == 0.8


class TestDeriveRecommendation:
    def test_strong_yes(self) -> None:
        assert _derive_recommendation(0.8, []) == ScreeningRecommendation.STRONG_YES

    def test_yes(self) -> None:
        assert _derive_recommendation(0.6, [_ev("a", 1.0, 50)]) == ScreeningRecommendation.YES

    def test_borderline(self) -> None:
        assert _derive_recommendation(0.4, []) == ScreeningRecommendation.BORDERLINE

    def test_no(self) -> None:
        assert _derive_recommendation(0.1, []) == ScreeningRecommendation.NO

    def test_strong_no(self) -> None:
        assert _derive_recommendation(0.0, []) == ScreeningRecommendation.STRONG_NO

    def test_must_have_fail_forces_strong_no(self) -> None:
        evals = [_ev("a", 1.0, 50), _ev("b", 0.0, 50, must_have=True)]
        assert _derive_recommendation(0.5, evals) == ScreeningRecommendation.STRONG_NO


class TestThresholds:
    def test_auto_advance_threshold(self) -> None:
        assert THRESHOLD_AUTO_ADVANCE == 0.6

    def test_auto_reject_threshold(self) -> None:
        assert THRESHOLD_AUTO_REJECT == 0.2


# ---------------------------------------------------------------------------
# Aggregate: ScreeningResult
# ---------------------------------------------------------------------------


class TestScreeningResultLevel0Reject:
    def test_create_level0_reject(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        result = ScreeningResult.create_level0_reject(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            level0=Level0Result(rejected=True, reason="spam", matched_rules=["spam"]),
        )
        assert result.status == ScreeningStatus.COMPLETED
        assert result.recommendation == ScreeningRecommendation.REJECTED_LEVEL0
        assert result.total_score == 0.0
        assert result.non_ai is False
        assert result.level0 is not None
        assert result.level0.reason == "spam"
        assert result.evaluations == []
        assert result.completed_at is not None

    def test_level0_reject_emits_event(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        result = ScreeningResult.create_level0_reject(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            level0=Level0Result(rejected=True, reason="blacklisted"),
        )
        events = result.collect_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "ScreeningCompleted"


class TestScreeningResultCompleted:
    def test_create_completed(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        evals = [_ev("Python", 1.0, 50), _ev("FastAPI", 1.0, 50)]
        result = ScreeningResult.create_completed(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            evaluations=evals,
            criteria_provenance_id=ProvenanceId.generate(),
            provenance_id=ProvenanceId.generate(),
            summary="Strong candidate",
            confidence=0.9,
        )
        assert result.status == ScreeningStatus.COMPLETED
        assert result.total_score == 1.0
        assert result.recommendation == ScreeningRecommendation.STRONG_YES
        assert result.confidence == 0.9
        assert result.non_ai is False
        assert len(result.evaluations) == 2

    def test_completed_emits_event(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        result = ScreeningResult.create_completed(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            evaluations=[_ev("a", 1.0, 100)],
            criteria_provenance_id=None,
            provenance_id=None,
            summary="test",
        )
        events = result.collect_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "ScreeningCompleted"


class TestScreeningResultMutations:
    def test_mark_stale(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        result = ScreeningResult.create_completed(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            evaluations=[_ev("a", 1.0, 100)],
            criteria_provenance_id=None,
            provenance_id=None,
            summary="test",
        )
        assert not result.is_stale
        result.mark_stale()
        assert result.is_stale
        assert result.status == ScreeningStatus.STALE

    def test_override_confirm(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        result = ScreeningResult.create_completed(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            evaluations=[_ev("a", 1.0, 100)],
            criteria_provenance_id=None,
            provenance_id=None,
            summary="test",
        )
        result.collect_events()  # clear
        result.override(OverrideAction.CONFIRM, "user-123")
        assert result.status == ScreeningStatus.OVERRIDDEN
        assert result.override_action == OverrideAction.CONFIRM
        assert result.overridden_by == "user-123"
        events = result.collect_events()
        assert len(events) == 1
        assert events[0].__class__.__name__ == "ScreeningOverridden"

    def test_override_dispute(self) -> None:
        app_id, cand_id, vac_id = _make_ids()
        result = ScreeningResult.create_completed(
            tenant_id=TENANT,
            application_id=app_id,
            candidate_id=cand_id,
            vacancy_id=vac_id,
            evaluations=[_ev("a", 0.5, 100)],
            criteria_provenance_id=None,
            provenance_id=None,
            summary="test",
        )
        result.override(OverrideAction.DISPUTE, "user-456")
        assert result.override_action == OverrideAction.DISPUTE
        assert result.overridden_by == "user-456"
