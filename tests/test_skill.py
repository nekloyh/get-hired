from __future__ import annotations

import pytest

from interview_coach.evaluator import Evaluation, PanelOpinion, PanelTrace
from interview_coach.skill import (
    CONFIDENCE_WEIGHT_FLOOR,
    EVIDENCE_WEIGHT,
    SkillState,
    aggregate_evidence_weight,
    apply_evaluation,
    apply_evaluations,
    confidence_weight,
    evidence_weight_for,
    panel_agreement_weight,
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


def _opinion(score: float) -> PanelOpinion:
    return PanelOpinion(recommended_score=score, argument="one-paragraph scorecard", key_evidence="quoted words")


def _panel_evaluation(weighted_score: float, *, disagreement: float, confidence: float = 0.9) -> Evaluation:
    """An escalated Evaluation with a committee trace attached the way evaluate() attaches it.

    ``panel`` is a derived field: the before-validator strips it from constructor input, so it must
    arrive via ``model_copy`` — same path as production (issue 0027).
    """
    trace = PanelTrace(
        triggers=("low_confidence",),
        skeptic=_opinion(2.0),
        advocate=_opinion(min(5.0, 2.0 + disagreement)),
        initial_score=weighted_score,
        initial_confidence=confidence,
        disagreement=disagreement,
    )
    return _evaluation(weighted_score, confidence).model_copy(update={"panel": trace})


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


def test_panel_agreement_weight_is_parity_at_consensus():
    # Full committee consensus must weigh exactly like a fully-confident unescalated judgment
    # (issue 0027: escalation itself is not a penalty — only a *split* committee is).
    assert panel_agreement_weight(0.0) == pytest.approx(EVIDENCE_WEIGHT)


def test_panel_agreement_weight_is_strictly_decreasing():
    assert (
        panel_agreement_weight(0.0)
        > panel_agreement_weight(1.0)
        > panel_agreement_weight(2.5)
        > panel_agreement_weight(4.0)
    )


def test_panel_agreement_weight_floor_is_weak_not_zero():
    # A maximally split committee is still *weak* evidence, not *no* evidence — the same floor
    # philosophy as confidence_weight (issue 0021).
    assert panel_agreement_weight(4.0) == pytest.approx(EVIDENCE_WEIGHT * CONFIDENCE_WEIGHT_FLOOR)
    assert panel_agreement_weight(4.0) > 0.0


def test_panel_agreement_weight_clamps_out_of_range():
    assert panel_agreement_weight(6.0) == pytest.approx(panel_agreement_weight(4.0))
    assert panel_agreement_weight(-1.0) == pytest.approx(panel_agreement_weight(0.0))


def test_evidence_weight_for_dispatches_panel_over_confidence():
    # The single source of truth (issues 0021/0027): a panel-escalated judgment weighs by committee
    # agreement — even a confident verdict on a split committee weighs less; an unescalated one
    # weighs by the Evaluator's confidence.
    plain = _evaluation(4.0, confidence=0.6)
    assert evidence_weight_for(plain) == pytest.approx(confidence_weight(0.6))

    contested = _panel_evaluation(4.0, disagreement=4.0, confidence=1.0)
    assert evidence_weight_for(contested) == pytest.approx(panel_agreement_weight(4.0))
    assert evidence_weight_for(contested) < confidence_weight(1.0)


def test_contested_verdict_moves_posterior_less_than_consensus_at_identical_score():
    # The property issue 0027 promises: same verdict score, but a committee that split moves the
    # Beta strictly less than one that converged.
    before = SkillState.neutral("ml_fundamentals")
    consensus = apply_evaluation(before, _panel_evaluation(5.0, disagreement=0.0))
    contested = apply_evaluation(before, _panel_evaluation(5.0, disagreement=3.0))
    assert consensus.mastery > contested.mastery > before.mastery


# --- R-24: the question, not the turn, is the unit of evidence -----------------------------------


def test_single_turn_fold_is_bit_identical_to_the_pre_r24_update():
    # The compatibility pin, and it must be EXACT, not approx: a one-turn question divides by 1.0,
    # which is lossless in IEEE-754, so every existing checkpoint and golden reproduces byte for
    # byte. This is the tripwire if anyone later swaps the divisor for a normalised-total or softmax
    # scheme that only *looks* equal at n=1.
    #
    # The pre-R-24 formula is spelled out here rather than called through ``apply_evaluation``,
    # which today delegates to ``apply_evaluations`` — comparing the two would be a tautology that
    # holds no matter what the fold does.
    neutral = SkillState.neutral("ml_fundamentals")
    ev = _evaluation(4.0, confidence=0.7)
    pre_r24 = neutral.observe(score_to_quality(4.0), weight=evidence_weight_for(ev))

    folded = apply_evaluations(neutral, [ev])

    assert (folded.alpha, folded.beta) == (pre_r24.alpha, pre_r24.beta)
    assert folded == apply_evaluation(neutral, ev)  # and the one-item wrapper stays a wrapper


def test_turn_count_never_multiplies_a_questions_evidence():
    # The whole reason the fold divides by len(turns): the number of turns is the Evaluator's
    # chattiness, not the Candidate's competence. Folding each turn at full weight would let a
    # 4-turn question outvote a 1-turn one 4:1 (8.0 pseudo-counts vs 2.0) for a reason no candidate
    # can influence — that naive fix is exactly what this test rejects.
    neutral = SkillState.neutral("ml_fundamentals")
    ev = _evaluation(4.0, confidence=1.0)

    one = apply_evaluations(neutral, [ev])
    four = apply_evaluations(neutral, [ev] * 4)

    assert four.alpha + four.beta == pytest.approx(one.alpha + one.beta)
    assert four.alpha + four.beta - (neutral.alpha + neutral.beta) == pytest.approx(EVIDENCE_WEIGHT)


def test_a_low_confidence_question_folds_the_floor_regardless_of_turn_count():
    # "~EVIDENCE_WEIGHT per question ± floor effects": a wholly unconfident 3-turn exchange still
    # adds the floor's worth of evidence, not three times it and not zero.
    neutral = SkillState.neutral("ml_fundamentals")
    shaky = _evaluation(4.0, confidence=0.0)

    folded = apply_evaluations(neutral, [shaky] * 3)

    added = folded.alpha + folded.beta - (neutral.alpha + neutral.beta)
    assert added == pytest.approx(EVIDENCE_WEIGHT * CONFIDENCE_WEIGHT_FLOOR)


def test_aggregate_evidence_weight_equals_the_pseudo_counts_folded():
    # The export's ``evidence_weight`` and the belief update must not be able to drift apart: this
    # asserts the reported total IS the total that moved the Beta, for a mixed question (one plain
    # low-confidence turn, one panel-escalated turn) where the two dispatches disagree.
    neutral = SkillState.neutral("ml_fundamentals")
    evaluations = [_evaluation(4.0, confidence=0.3), _panel_evaluation(4.0, disagreement=3.5)]

    folded = apply_evaluations(neutral, evaluations)

    added = folded.alpha + folded.beta - (neutral.alpha + neutral.beta)
    assert aggregate_evidence_weight(evaluations) == pytest.approx(added)


def test_panel_and_plain_turns_keep_their_own_dispatch_inside_a_question():
    # A question can mix an unescalated seed turn with a panel-escalated follow-up. Each turn must
    # still weigh by *its own* signal (0021 confidence vs 0027 committee agreement); collapsing the
    # question onto a single dispatch would silently re-price the escalated turn.
    neutral = SkillState.neutral("ml_fundamentals")
    plain = _evaluation(5.0, confidence=0.9)
    contested = _panel_evaluation(5.0, disagreement=4.0, confidence=0.9)

    folded = apply_evaluations(neutral, [plain, contested])

    expected = neutral.observe(1.0, weight=confidence_weight(0.9) / 2.0).observe(
        1.0, weight=panel_agreement_weight(4.0) / 2.0
    )
    assert (folded.alpha, folded.beta) == (expected.alpha, expected.beta)
    # And the escalated turn really was discounted: pricing it by confidence instead would have
    # folded strictly more evidence.
    by_confidence = apply_evaluations(neutral, [plain, _evaluation(5.0, confidence=0.9)])
    assert folded.alpha + folded.beta < by_confidence.alpha + by_confidence.beta


def test_a_question_with_no_turns_is_a_programming_error():
    # A question that scored nothing must never reach the fold: the FAILED path keeps the prior and
    # skips the update entirely (ADR 0005). Silently returning the state unchanged would hide a
    # caller that lost its turns.
    with pytest.raises(ValueError):
        apply_evaluations(SkillState.neutral("ml_fundamentals"), [])


def test_aggregate_evidence_weight_of_no_turns_is_zero_evidence():
    # The export's counterpart to the above: a failed question reports zero weight, never a crash.
    assert aggregate_evidence_weight([]) == 0.0


# --- R-20: the single rehydration point ----------------------------------------------------------


def test_from_dict_coerces_json_round_tripped_values():
    # Old checkpoints carry ints and, historically, stringly numbers.
    state = SkillState.from_dict({"skill": "mlops", "alpha": 1, "beta": "2"})

    assert state == SkillState(skill="mlops", alpha=1.0, beta=2.0)


@pytest.mark.parametrize("missing", ["skill", "alpha", "beta"])
def test_from_dict_raises_rather_than_inventing_a_neutral_prior(missing):
    # Silently falling back to Beta(1,1) would put a plausible-looking 50% mastery in a report,
    # which is worse than a KeyError precisely because nobody would question it.
    raw = {"skill": "mlops", "alpha": 2.0, "beta": 3.0}
    del raw[missing]

    with pytest.raises(KeyError):
        SkillState.from_dict(raw)


def test_from_dict_keeps_the_positivity_check():
    with pytest.raises(ValueError, match="must both be > 0"):
        SkillState.from_dict({"skill": "mlops", "alpha": 0, "beta": 1})


def test_to_dict_round_trips_and_keeps_writer_key_order():
    state = SkillState(skill="mlops", alpha=2.5, beta=1.5)

    assert list(state.to_dict()) == ["skill", "alpha", "beta"]
    assert SkillState.from_dict(state.to_dict()) == state
