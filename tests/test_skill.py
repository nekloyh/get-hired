from __future__ import annotations

import pytest

from interview_coach.evaluator import Evaluation
from interview_coach.skill import SkillState, apply_evaluation, score_to_quality


def _evaluation(weighted_score: float) -> Evaluation:
    """A minimal Evaluation carrying just the weighted_score the updater reads."""
    return Evaluation(
        dimensions={},
        weighted_score=weighted_score,
        confidence=0.9,
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
