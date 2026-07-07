from __future__ import annotations

import pytest

from interview_coach.evaluator import Evaluation
from interview_coach.skill import (
    EVIDENCE_WEIGHT,
    SkillState,
    apply_evaluation,
    confidence_weight,
    score_to_quality,
)


def _evaluation(weighted_score: float, confidence: float = 0.9) -> Evaluation:
    """A minimal Evaluation carrying just the weighted_score + confidence the updater reads."""
    return Evaluation(
        dimensions={},
        weighted_score=weighted_score,
        confidence=confidence,
        follow_up_recommended=False,
        follow_up_rationale="n/a",
    )


def test_neutral_prior_is_uniform():
    s = SkillState.neutral("ml_fundamentals")
    assert s.mastery == pytest.approx(0.5)
    assert s.confidence == pytest.approx(0.0)  # no evidence -> no confidence


def test_score_to_quality_maps_1_5_onto_0_1():
    assert score_to_quality(1) == pytest.approx(0.0)
    assert score_to_quality(3) == pytest.approx(0.5)
    assert score_to_quality(5) == pytest.approx(1.0)


def test_strong_answer_raises_mastery():
    before = SkillState.neutral("ml_fundamentals")
    after = apply_evaluation(before, _evaluation(5))
    assert after.mastery > before.mastery


def test_weak_answer_lowers_mastery():
    before = SkillState.neutral("ml_fundamentals")
    after = apply_evaluation(before, _evaluation(1))
    assert after.mastery < before.mastery


def test_strong_and_weak_move_in_opposite_directions():
    neutral = SkillState.neutral("ml_fundamentals")
    strong = apply_evaluation(neutral, _evaluation(5))
    weak = apply_evaluation(neutral, _evaluation(1))
    assert strong.mastery > neutral.mastery > weak.mastery


def test_any_evaluation_increases_confidence():
    before = SkillState.neutral("ml_fundamentals")
    # A middling score leaves the mean put but still adds evidence -> confidence must rise.
    after = apply_evaluation(before, _evaluation(3))
    assert after.mastery == pytest.approx(before.mastery)  # quality 0.5 -> mean unchanged
    assert after.confidence > before.confidence


def test_more_evidence_raises_confidence_further():
    s0 = SkillState.neutral("ml_fundamentals")
    s1 = apply_evaluation(s0, _evaluation(5))
    s2 = apply_evaluation(s1, _evaluation(5))
    assert s2.confidence > s1.confidence > s0.confidence


def test_update_is_deterministic_and_pure():
    before = SkillState.neutral("ml_fundamentals")
    a = apply_evaluation(before, _evaluation(4))
    b = apply_evaluation(before, _evaluation(4))
    assert (a.alpha, a.beta) == (b.alpha, b.beta)
    assert (before.alpha, before.beta) == (1.0, 1.0)  # frozen: original untouched


def test_confidence_weight_is_parity_at_full_confidence():
    # Full confidence must reproduce the fixed-weight era exactly (issue 0021: no silent recalibration).
    assert confidence_weight(1.0) == pytest.approx(EVIDENCE_WEIGHT)


def test_confidence_weight_is_strictly_monotonic():
    assert confidence_weight(0.2) < confidence_weight(0.5) < confidence_weight(0.9) < confidence_weight(1.0)


def test_confidence_weight_floor_is_weak_not_zero():
    # A zero-confidence judgment is weak evidence, not no evidence — still positive, still < full.
    assert 0.0 < confidence_weight(0.0) < confidence_weight(1.0)


def test_confidence_weight_clamps_out_of_range():
    assert confidence_weight(1.5) == pytest.approx(confidence_weight(1.0))
    assert confidence_weight(-0.3) == pytest.approx(confidence_weight(0.0))


def test_lower_confidence_moves_posterior_less_at_identical_score():
    # The property issue 0021 promises: same score, lower confidence ⇒ strictly smaller posterior shift.
    before = SkillState.neutral("ml_fundamentals")
    high = apply_evaluation(before, _evaluation(5, confidence=0.95))
    low = apply_evaluation(before, _evaluation(5, confidence=0.30))
    assert high.mastery > low.mastery > before.mastery  # both raise mastery, high raises it more


def test_observe_splits_weight_by_quality():
    s = SkillState.neutral("ml_fundamentals").observe(1.0, weight=4.0)
    assert s.alpha == pytest.approx(5.0)  # all weight to success
    assert s.beta == pytest.approx(1.0)


def test_observe_rejects_out_of_range_inputs():
    s = SkillState.neutral("ml_fundamentals")
    with pytest.raises(ValueError):
        s.observe(1.5)
    with pytest.raises(ValueError):
        s.observe(0.5, weight=0.0)


def test_skill_state_rejects_nonpositive_params():
    with pytest.raises(ValueError):
        SkillState(skill="x", alpha=0.0, beta=1.0)
