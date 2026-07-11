from __future__ import annotations

import json
import logging
import unicodedata

import pytest

from interview_coach.config import load_settings
from interview_coach.evaluator import (
    DIVERGENCE_CONFIDENCE_CEILING,
    EVIDENCE_DEGRADE_CONFIDENCE_CEILING,
    SELF_CRITIQUE_CONFIDENCE_THRESHOLD,
    UNVERIFIABLE_EVIDENCE,
    WEIGHTED_SCORE_TOLERANCE,
    DimensionScore,
    Evaluation,
    apply_cross_check,
    evaluate,
    linear_weighted_score,
)
from interview_coach.fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from interview_coach.llm import build_client
from interview_coach.rubric import Rubric

ACTIVE = {"correctness", "depth", "communication", "system_thinking"}


def _good_dimensions() -> dict:
    # Each 'evidence' is a verbatim substring of STRONG_ANSWER.
    return {
        "correctness": {"score": 5, "evidence": "Bias is error from overly simple assumptions"},
        "depth": {"score": 4, "evidence": "I use learning curves to tell them apart"},
        "communication": {
            "score": 4,
            "evidence": "A high-bias model like plain linear regression underfits",
        },
        "system_thinking": {"score": 4, "evidence": "L2 shrinks weights to reduce variance"},
    }


def _weak_dimensions() -> dict:
    # All active dimensions score 2 -> a linear weighted score of 2.0 under QUESTION.rubric.
    return {d: {"score": 2, "evidence": "no evidence"} for d in ACTIVE}


def _eval_json(dimensions: dict, weighted: float = 4.0, confidence: float = 0.8) -> str:
    return json.dumps(
        {
            "dimensions": dimensions,
            "weighted_score": weighted,
            "confidence": confidence,
            "follow_up_recommended": False,
            "follow_up_rationale": "The answer is fully revealed.",
        }
    )


def _evaluation(scores: dict[str, int], weighted: float, confidence: float = 0.8) -> Evaluation:
    """Build an Evaluation directly (bypassing the LLM) to exercise the cross-check in isolation."""
    return Evaluation(
        dimensions={d: DimensionScore(score=s, evidence="no evidence") for d, s in scores.items()},
        weighted_score=weighted,
        confidence=confidence,
        follow_up_recommended=False,
        follow_up_rationale="n/a",
    )


def test_evaluate_happy_path(make_client):
    client, fake = make_client([_eval_json(_good_dimensions())])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert isinstance(ev, Evaluation)
    assert set(ev.dimensions) == ACTIVE
    assert "mlops_awareness" not in ev.dimensions  # weight 0 -> not scored
    assert fake.call_count == 1


def test_system_prompt_enforces_language_invariance():
    # issue 0031 / #35: the judge scored VN answers inconsistently from their EN twins. The fix is a
    # prompt instruction that language must not affect the score; the calibration bench is the
    # behavioral gate, and this offline check locks the contract so it can't be silently dropped.
    from interview_coach.evaluator import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "language must not affect the score" in lowered
    assert "vietnamese" in lowered  # the instruction names the language it must not penalise


def test_weight_zero_dimension_rejected_then_corrected(make_client):
    bad = _good_dimensions() | {"mlops_awareness": {"score": 3, "evidence": "no evidence"}}
    client, fake = make_client([_eval_json(bad), _eval_json(_good_dimensions())])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert "mlops_awareness" not in ev.dimensions
    assert fake.call_count == 2  # retried after the weight-0 violation


def test_non_verbatim_evidence_rejected_then_corrected(make_client):
    bad = _good_dimensions()
    bad["correctness"] = {"score": 5, "evidence": "the candidate clearly understands this topic"}
    client, fake = make_client([_eval_json(bad), _eval_json(_good_dimensions())])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.dimensions["correctness"].evidence == "Bias is error from overly simple assumptions"
    assert fake.call_count == 2


def test_case_changed_evidence_rejected_then_corrected(make_client):
    bad = _good_dimensions()
    bad["correctness"] = {
        "score": 5,
        "evidence": "bias is error from overly simple assumptions",
    }
    client, fake = make_client([_eval_json(bad), _eval_json(_good_dimensions())])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.dimensions["correctness"].evidence == "Bias is error from overly simple assumptions"
    assert fake.call_count == 2


def test_non_contiguous_evidence_rejected_then_corrected(make_client):
    bad = _good_dimensions()
    bad["correctness"] = {
        "score": 5,
        "evidence": (
            "Bias is error from overly simple assumptions. "
            "L2 shrinks weights to reduce variance"
        ),
    }

    client, fake = make_client([_eval_json(bad), _eval_json(_good_dimensions())])

    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    assert ev.dimensions["correctness"].evidence == "Bias is error from overly simple assumptions"
    assert fake.call_count == 2


def test_evidence_retry_prompt_includes_candidate_answer_and_contiguous_rule(make_client):
    # Non-contiguous evidence (two real phrases stitched together) is the live failure mode. The
    # retry correction must hand the model the source answer + the exact rule so the repair is
    # actionable, not just "that was invalid".
    bad = _good_dimensions()
    bad["correctness"] = {
        "score": 5,
        "evidence": (
            "Bias is error from overly simple assumptions. "
            "L2 shrinks weights to reduce variance"
        ),
    }

    client, fake = make_client([_eval_json(bad), _eval_json(_good_dimensions())])

    evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    retry_msg = fake.chat.completions.calls[1]["messages"][-1]["content"]
    assert "CANDIDATE ANSWER" in retry_msg
    assert STRONG_ANSWER in retry_msg
    assert "ONE contiguous substring" in retry_msg


def test_no_evidence_is_allowed(make_client):
    dims = _good_dimensions()
    dims["system_thinking"] = {"score": 2, "evidence": "no evidence"}
    client, _ = make_client([_eval_json(dims)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.dimensions["system_thinking"].evidence == "no evidence"


def _single_dim_eval(evidence: str) -> str:
    # One-dimension rubric keeps weighted_score == the dimension score (no cross-check, no critique),
    # so call_count isolates exactly whether the evidence gate accepted the quote on the first attempt.
    return _single_dim_eval_conf(evidence, confidence=0.9)


def _single_dim_eval_conf(evidence: str, *, confidence: float) -> str:
    return json.dumps(
        {
            "dimensions": {"correctness": {"score": 5, "evidence": evidence}},
            "weighted_score": 5.0,
            "confidence": confidence,
            "follow_up_recommended": False,
            "follow_up_rationale": "n/a",
        }
    )


def test_whitespace_reflowed_evidence_accepted_without_a_retry(make_client):
    # The model commonly reflows a verbatim span across a line break, joining it with a space. That is
    # a faithful quote, so the gate must accept it on the FIRST attempt rather than burning a retry.
    answer = "Bias is systematic error from\ntoo-simple assumptions, while variance\nis sensitivity."
    rubric = Rubric(weights={"correctness": 1.0})
    client, fake = make_client([_single_dim_eval("systematic error from too-simple assumptions")])

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert ev.dimensions["correctness"].evidence == "systematic error from too-simple assumptions"
    assert fake.call_count == 1  # accepted first time — no retry


def test_smart_quote_evidence_accepted_without_a_retry(make_client):
    # The model renders straight quotes as smart quotes; that is cosmetic, so the gate accepts it.
    answer = 'He framed it as "too-simple" assumptions causing bias.'
    rubric = Rubric(weights={"correctness": 1.0})
    client, fake = make_client([_single_dim_eval("“too-simple” assumptions")])

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert fake.call_count == 1
    assert ev.dimensions["correctness"].evidence == "“too-simple” assumptions"  # original text kept


def test_tolerant_match_still_rejects_a_paraphrase(make_client):
    # The fold is whitespace + quote glyphs only — never word content — so a paraphrase still fails and
    # is retried, preserving the anti-fabrication guarantee.
    answer = "Bias is systematic error from too-simple assumptions."
    rubric = Rubric(weights={"correctness": 1.0})
    client, fake = make_client(
        [_single_dim_eval("bias comes from oversimplified models"), _single_dim_eval("systematic error")]
    )

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert ev.dimensions["correctness"].evidence == "systematic error"
    assert fake.call_count == 2  # paraphrase rejected, corrected on retry


def test_nfc_normalized_vietnamese_evidence_accepted_without_a_retry(make_client):
    # A character-perfect Vietnamese quote can arrive in a different Unicode composition form (NFD)
    # than the source (NFC) — a faithful copy that a naive substring test wrongly rejects. This was
    # the live cause of the bench's strong Vietnamese case failing. NFC-folding must accept it on the
    # FIRST attempt.
    answer = unicodedata.normalize("NFC", "Phân đoạn từ tiếng Việt cần xử lý dấu thanh cẩn thận.")
    span = unicodedata.normalize("NFC", "xử lý dấu thanh")
    assert span in answer
    nfd_quote = unicodedata.normalize("NFD", span)
    assert nfd_quote != span  # the model emitted a different composition form
    rubric = Rubric(weights={"correctness": 1.0})
    client, fake = make_client([_single_dim_eval(nfd_quote)])

    ev = evaluate(client, "Explain VN segmentation.", answer, rubric)

    assert fake.call_count == 1  # accepted despite the NFD/NFC mismatch — no retry burned
    assert ev.dimensions["correctness"].score == 5


def test_persistently_unverifiable_evidence_degrades_instead_of_crashing(make_client):
    # gpt-4o-mini's live failure: on long strong answers it keeps paraphrasing its citation even after
    # the enforced retry, which used to raise StructuredOutputError and lose the whole valid score.
    # The evidence is an audit trail, so the judge must degrade — blank the quote, keep the score —
    # never crash on an otherwise-valid answer.
    answer = "Bias is systematic error from too-simple assumptions."
    rubric = Rubric(weights={"correctness": 1.0})
    client, fake = make_client([_single_dim_eval("the model oversimplifies the data")])  # never verbatim

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert ev.dimensions["correctness"].score == 5  # score preserved
    assert ev.dimensions["correctness"].evidence == UNVERIFIABLE_EVIDENCE  # citation blanked, not crashed
    assert fake.call_count == 3  # 2 enforced attempts fail evidence, then 1 degrade pass without it


# --- evidence-degrade confidence signal (issue 0033 / GH #37) ----------------------------------


def _two_dim_eval(corr_evidence: str, depth_evidence: str, *, confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "dimensions": {
                "correctness": {"score": 5, "evidence": corr_evidence},
                "depth": {"score": 4, "evidence": depth_evidence},
            },
            "weighted_score": 4.6,
            "confidence": confidence,
            "follow_up_recommended": False,
            "follow_up_rationale": "n/a",
        }
    )


def test_entirely_unverifiable_evidence_flags_degraded_and_caps_confidence(make_client):
    # The hardening for issue 0033: when EVERY citation is unverifiable and blanked, that is a strong
    # hallucination signal. The score is still kept (a valid judgment must not be lost to a bad quote),
    # but the judgment must no longer read as full-confidence — it carries evidence_degraded=True and
    # its confidence is capped low, mirroring the weighted-score cross-check ceiling.
    answer = "Bias is systematic error from too-simple assumptions."
    rubric = Rubric(weights={"correctness": 1.0})
    client, _ = make_client([_single_dim_eval("the model oversimplifies the data")])  # never verbatim

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert ev.dimensions["correctness"].score == 5  # score preserved
    assert ev.dimensions["correctness"].evidence == UNVERIFIABLE_EVIDENCE
    assert ev.evidence_degraded is True
    assert ev.confidence <= EVIDENCE_DEGRADE_CONFIDENCE_CEILING  # full 0.9 confidence no longer stands


def test_partial_citation_blanking_is_not_flagged_and_keeps_confidence(make_client):
    # A judgment with SOME verifiable evidence still has a partial audit trail — the current
    # "sanitize-and-keep" behavior is correct there. Only an *entirely* fabricated trail trips the
    # degrade signal, so a partial blank must not flag or haircut.
    answer = "Bias is systematic error from too-simple assumptions."
    rubric = Rubric(weights={"correctness": 0.6, "depth": 0.4})
    # correctness quotes verbatim; depth paraphrases -> the enforced check fails, then degrade blanks
    # only depth. Two attempts fail the evidence gate, then one degrade pass runs without it.
    verbatim = "systematic error from too-simple assumptions"
    paraphrase = "the answer lacks nuance"
    client, fake = make_client(
        [_two_dim_eval(verbatim, paraphrase), _two_dim_eval(verbatim, paraphrase)]
    )

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert ev.dimensions["correctness"].evidence == verbatim  # verifiable citation kept
    assert ev.dimensions["depth"].evidence == UNVERIFIABLE_EVIDENCE  # only the bad one blanked
    assert ev.evidence_degraded is False  # audit trail only partially unverifiable
    assert ev.confidence == pytest.approx(0.9)  # not capped


def test_happy_path_is_not_evidence_degraded(make_client):
    # A judgment whose citations all verify carries evidence_degraded=False and keeps its confidence.
    client, _ = make_client([_eval_json(_good_dimensions(), confidence=0.9)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    assert ev.evidence_degraded is False
    assert ev.confidence == pytest.approx(0.9)


def test_evidence_degrade_ceiling_only_lowers_confidence(make_client):
    # The haircut uses min(): a judgment already less confident than the ceiling is left untouched,
    # exactly like the cross-check guard — the degrade signal never raises confidence. A confidence
    # below the ceiling is also below the escalation threshold, so the panel inevitably runs; the
    # property must hold on the verdict, which here goes through the same degrade dance as the
    # first pass (2 evidence failures + 1 degrade pass each), with the committee in between.
    answer = "Bias is systematic error from too-simple assumptions."
    rubric = Rubric(weights={"correctness": 1.0})
    low = EVIDENCE_DEGRADE_CONFIDENCE_CEILING / 2
    bad = _single_dim_eval_conf("the model oversimplifies", confidence=low)
    opinion = json.dumps(
        {
            "recommended_score": 4.0,
            "argument": "Committee voice scorecard.",
            "key_evidence": "too-simple assumptions",
        }
    )
    client, fake = make_client([bad, bad, bad, opinion, opinion, bad, bad, bad])

    ev = evaluate(client, "Explain bias.", answer, rubric)

    assert ev.evidence_degraded is True
    assert ev.panel is not None  # low confidence always escalates now (issue 0027)
    assert ev.confidence == pytest.approx(low)  # already below the ceiling; unchanged
    assert fake.call_count == 8


# --- weighted_score cross-check guard (slice 0003) ---------------------------------------------


def test_linear_weighted_score_normalizes_by_active_weights():
    # (3*5 + 1*1) / (3 + 1) = 16 / 4 = 4.0 — weights need not sum to 1.
    rubric = Rubric(weights={"correctness": 3.0, "depth": 1.0})
    dims = {
        "correctness": DimensionScore(score=5, evidence="x"),
        "depth": DimensionScore(score=1, evidence="x"),
    }
    assert linear_weighted_score(dims, rubric) == pytest.approx(4.0)


def test_cross_check_leaves_confidence_when_scores_agree():
    # Dimensions {5,4,4,4} under QUESTION.rubric give a linear 4.4; holistic 4.0 is within tolerance.
    ev = _evaluation({"correctness": 5, "depth": 4, "communication": 4, "system_thinking": 4}, 4.0)
    guarded = apply_cross_check(ev, QUESTION.rubric)
    assert guarded.confidence == ev.confidence
    assert guarded is ev  # untouched: same object returned


def test_cross_check_at_tolerance_boundary_does_not_trip():
    # linear = 2.0, holistic = 3.0 -> divergence exactly == tolerance (1.0), which must NOT trip.
    ev = _evaluation({d: 2 for d in ACTIVE}, 2.0 + WEIGHTED_SCORE_TOLERANCE, confidence=0.9)
    assert apply_cross_check(ev, QUESTION.rubric).confidence == pytest.approx(0.9)


def test_cross_check_inflated_score_drops_confidence():
    # Weak dimensions (linear 2.0) but an inflated holistic 4.5 -> the hole the guard closes.
    ev = _evaluation({d: 2 for d in ACTIVE}, 4.5, confidence=0.9)
    guarded = apply_cross_check(ev, QUESTION.rubric)
    assert guarded.confidence == pytest.approx(DIVERGENCE_CONFIDENCE_CEILING)
    assert guarded.confidence < ev.confidence
    assert guarded.weighted_score == ev.weighted_score  # the holistic score is kept, not overwritten


def test_cross_check_is_symmetric_a_sharp_downward_cap_also_trips():
    # Strong dimensions (linear 5.0) but the model caps the answer at 2.0 -> divergence is flagged too.
    ev = _evaluation({d: 5 for d in ACTIVE}, 2.0, confidence=0.9)
    assert apply_cross_check(ev, QUESTION.rubric).confidence == pytest.approx(DIVERGENCE_CONFIDENCE_CEILING)


def test_cross_check_does_not_raise_already_low_confidence():
    # Divergent, but the model was already unsure (<= ceiling) -> left exactly as-is, never raised.
    ev = _evaluation({d: 2 for d in ACTIVE}, 4.5, confidence=0.1)
    guarded = apply_cross_check(ev, QUESTION.rubric)
    assert guarded.confidence == pytest.approx(0.1)
    assert guarded is ev


def test_cross_check_runs_inside_evaluate(make_client):
    # Wiring: an inflated holistic score lowers confidence and trips the divergence trigger, which
    # now escalates to the panel (issue 0027): Skeptic + Advocate advise, then the verdict pass.
    client, fake = make_client(
        [
            _eval_json(_weak_dimensions(), weighted=4.5, confidence=0.9),
            _panel_opinion_json(2.0, stance="skeptic"),
            _panel_opinion_json(3.0, stance="advocate"),
            _eval_json(_weak_dimensions(), weighted=2.0, confidence=0.8),
        ]
    )
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.confidence == pytest.approx(0.8)
    assert ev.weighted_score == pytest.approx(2.0)
    assert ev.panel is not None
    assert "weighted_score_divergence" in ev.panel.triggers
    assert fake.call_count == 4


# --- escalation: Panel Verdict (issue 0027, superseding slice 0006's lone re-read) ---------------


def _panel_opinion_json(score: float, *, stance: str) -> str:
    return json.dumps(
        {
            "recommended_score": score,
            "argument": f"The {stance} argues the answer merits about {score:g}.",
            "key_evidence": "Bias is error from overly simple assumptions",
        }
    )


def test_low_confidence_escalates_to_the_panel(make_client):
    assert DIVERGENCE_CONFIDENCE_CEILING < SELF_CRITIQUE_CONFIDENCE_THRESHOLD
    client, fake = make_client(
        [
            _eval_json(_good_dimensions(), weighted=4.0, confidence=0.3),  # first pass (shaky)
            _panel_opinion_json(2.5, stance="skeptic"),
            _panel_opinion_json(4.5, stance="advocate"),
            _eval_json(_good_dimensions(), weighted=4.0, confidence=0.7),  # final verdict
        ]
    )

    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    assert ev.confidence == pytest.approx(0.7)
    assert ev.panel is not None
    assert ev.panel.triggers == ("low_confidence",)
    assert ev.panel.skeptic.recommended_score == pytest.approx(2.5)
    assert ev.panel.advocate.recommended_score == pytest.approx(4.5)
    assert ev.panel.disagreement == pytest.approx(2.0)
    assert ev.panel.initial_confidence == pytest.approx(0.3)
    assert ev.self_critique is None  # the lone re-read is superseded by the panel
    assert fake.call_count == 4  # first pass + skeptic + advocate + verdict


def test_high_confidence_does_not_trigger_self_critique(make_client):
    # THE cost gate (issue 0027 acceptance criterion): a confident score never pays panel calls.
    client, fake = make_client([_eval_json(_good_dimensions(), weighted=4.0, confidence=0.7)])

    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    assert ev.confidence == pytest.approx(0.7)
    assert ev.self_critique is None
    assert ev.panel is None
    assert fake.call_count == 1


def test_panel_verdict_is_kept_even_when_less_confident_than_the_first_pass(make_client):
    # ADR 0001: the Evaluator issues the final verdict HAVING READ both voices — the informed pass
    # is the verdict, not whichever pass felt more confident (that was the pre-panel behavior).
    client, fake = make_client(
        [
            _eval_json(_good_dimensions(), weighted=4.0, confidence=0.3),
            _panel_opinion_json(3.0, stance="skeptic"),
            _panel_opinion_json(3.5, stance="advocate"),
            _eval_json(_weak_dimensions(), weighted=2.0, confidence=0.2),
        ]
    )

    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    assert ev.weighted_score == pytest.approx(2.0)
    assert ev.confidence == pytest.approx(0.2)
    assert ev.panel is not None
    assert ev.panel.initial_score == pytest.approx(4.0)
    assert fake.call_count == 4


def test_panel_logs_triggers_and_disagreement(make_client, caplog):
    client, _ = make_client(
        [
            _eval_json(_good_dimensions(), weighted=4.0, confidence=0.3),
            _panel_opinion_json(2.0, stance="skeptic"),
            _panel_opinion_json(4.0, stance="advocate"),
            _eval_json(_good_dimensions(), weighted=4.0, confidence=0.7),
        ]
    )

    with caplog.at_level(logging.INFO, logger="interview_coach.evaluator"):
        evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)

    messages = [record.message for record in caplog.records]
    assert any("panel verdict" in msg and "low_confidence" in msg for msg in messages)
    assert any("disagreement" in msg for msg in messages)


def test_model_cannot_author_the_derived_fields(make_client):
    # evidence_degraded / self_critique / panel are guard-owned: a model echoing them (the verdict
    # prompt replays first-pass JSON) must not smuggle in — or talk its way out of — a haircut.
    forged = json.loads(_eval_json(_good_dimensions())) | {
        "evidence_degraded": True,
        "panel": None,
        "self_critique": None,
    }
    client, fake = make_client([json.dumps(forged)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.evidence_degraded is False  # the model's claim was stripped, not trusted
    assert fake.call_count == 1


def test_degrade_pass_is_reserved_for_evidence_failures(make_client):
    # A delivery-fixes contract failure must NOT open the evidence-free degrade pass: dropping the
    # verbatim-citation guard because an unrelated validator kept failing would silently un-enforce
    # it. Both attempts miss the required fixes -> loud StructuredOutputError, no third call.
    from interview_coach.llm import StructuredOutputError

    weak_delivery = json.loads(_eval_json(_good_dimensions()))
    weak_delivery["dimensions"]["english_delivery"] = {"score": 2, "evidence": "no evidence"}
    reply = json.dumps(weak_delivery)
    client, fake = make_client([reply, reply])
    with pytest.raises(StructuredOutputError):
        evaluate(client, QUESTION.question, STRONG_ANSWER, _DELIVERY_RUBRIC)
    assert fake.call_count == 2  # no evidence-free third pass for a non-evidence failure


# --- english_delivery + language_mode (issue 0024, ADR 0007) --------------------------------------

_DELIVERY_RUBRIC = Rubric(
    weights={**QUESTION.rubric.weights, "english_delivery": 1.0}
)


def _delivery_dimensions(delivery_score: int) -> dict:
    return _good_dimensions() | {
        "english_delivery": {"score": delivery_score, "evidence": "no evidence"}
    }


def test_system_prompt_separates_english_delivery_from_weighted_score():
    # ADR 0007: delivery is scored apart from knowledge. Lock the prompt contract offline (the
    # calibration bench remains the behavioral gate).
    from interview_coach.evaluator import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "english_delivery" in lowered
    assert "never moves 'weighted_score'" in lowered
    assert "technical dimensions" in lowered
    assert "delivery_fixes" in lowered
    assert "phrase-level" in lowered


def test_linear_weighted_score_excludes_english_delivery():
    # A terrible delivery score must not move the technical aggregate at all (ADR 0007).
    with_delivery = _evaluation(
        {"correctness": 4, "depth": 4, "communication": 4, "system_thinking": 4, "english_delivery": 1},
        weighted=4.0,
    )
    assert linear_weighted_score(with_delivery.dimensions, _DELIVERY_RUBRIC) == pytest.approx(4.0)


def test_weak_delivery_without_fixes_is_rejected_then_corrected(make_client):
    bad = _eval_json(_delivery_dimensions(2))
    good = json.dumps(
        json.loads(_eval_json(_delivery_dimensions(2)))
        | {"delivery_fixes": ['"model overfit" — "the model overfits"', "fix two", "fix three"]}
    )
    client, fake = make_client([bad, good])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, _DELIVERY_RUBRIC)
    assert len(ev.delivery_fixes) >= 3
    assert fake.call_count == 2  # retried after the missing-fixes violation


def test_strong_delivery_needs_no_fixes(make_client):
    client, fake = make_client([_eval_json(_delivery_dimensions(5))])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, _DELIVERY_RUBRIC)
    assert ev.dimensions["english_delivery"].score == 5
    assert ev.delivery_fixes == ()
    assert fake.call_count == 1


def test_stray_delivery_fixes_on_inactive_dimension_are_dropped_without_a_retry(make_client):
    # Seen live: the judge volunteers delivery advice on cases where english_delivery is not scored.
    # Structural noise is folded deterministically — no phantom advice, no burned retry.
    stray = json.dumps(
        json.loads(_eval_json(_good_dimensions())) | {"delivery_fixes": ["a", "b", "c"]}
    )
    client, fake = make_client([stray])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.delivery_fixes == ()
    assert fake.call_count == 1


def test_delivery_fixes_nested_inside_dimensions_are_recovered(make_client):
    # Seen live: gpt-5.4-mini nests delivery_fixes inside "dimensions" — a valid judgment must not
    # be lost to field placement.
    payload = json.loads(_eval_json(_delivery_dimensions(2)))
    payload["dimensions"]["delivery_fixes"] = ["fix one", "fix two", "fix three"]
    client, fake = make_client([json.dumps(payload)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, _DELIVERY_RUBRIC)
    assert ev.delivery_fixes == ("fix one", "fix two", "fix three")
    assert "delivery_fixes" not in ev.dimensions
    assert fake.call_count == 1


def test_delivery_fixes_wrong_type_is_coerced_to_empty(make_client):
    # {} / null instead of a list (seen live) reads as "no fixes offered", which the semantic
    # validator then handles: fine on a strong delivery, a retry-steering error on a weak one.
    payload = json.loads(_eval_json(_delivery_dimensions(5))) | {"delivery_fixes": {}}
    client, fake = make_client([json.dumps(payload)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, _DELIVERY_RUBRIC)
    assert ev.delivery_fixes == ()
    assert fake.call_count == 1


def test_schema_hint_mentions_delivery_fixes_only_when_active():
    from interview_coach.evaluator import _schema_hint

    assert "delivery_fixes" not in _schema_hint(QUESTION.rubric)
    assert "delivery_fixes" in _schema_hint(_DELIVERY_RUBRIC)
    assert "TOP-LEVEL" in _schema_hint(_DELIVERY_RUBRIC)


def test_system_prompt_mentions_english_delivery_only_when_active():
    # Seen live (gpt-5.4-mini, 2026-07-11): describing english_delivery on every case makes the
    # judge volunteer the dimension on delivery-less cases and burn both structured-output
    # attempts on the "do not score" validator. The rules ride along only when the rubric lists it.
    from interview_coach.evaluator import _build_messages

    plain = _build_messages("q", "a", QUESTION.rubric)[0]["content"]
    delivery = _build_messages("q", "a", _DELIVERY_RUBRIC)[0]["content"]
    assert "english_delivery" not in plain
    assert "english_delivery" in delivery
    assert "delivery_fixes" in delivery


def test_top_level_fields_nested_inside_dimensions_are_recovered(make_client):
    # Seen live (gpt-5.4-mini, 2026-07-11): on long answers the judge sometimes flattens the whole
    # judgment inside "dimensions" — weighted_score, confidence, and the follow-up fields arrive as
    # siblings of the dimension scores. Field placement must not cost a valid judgment or a retry.
    payload = json.loads(_eval_json(_good_dimensions(), weighted=4.0, confidence=0.9))
    for field in ("weighted_score", "confidence", "follow_up_recommended", "follow_up_rationale"):
        payload["dimensions"][field] = payload.pop(field)
    client, fake = make_client([json.dumps(payload)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.weighted_score == pytest.approx(4.0)
    assert ev.confidence == pytest.approx(0.9)
    assert set(ev.dimensions) == set(_good_dimensions())
    assert fake.call_count == 1


def test_language_mode_blocks_reach_the_judge_prompt(make_client):
    from interview_coach.evaluator import _build_messages

    en = _build_messages("q", "a", QUESTION.rubric, "en")[1]["content"]
    vn = _build_messages("q", "a", QUESTION.rubric, "vn")[1]["content"]
    mixed = _build_messages("q", "a", QUESTION.rubric, "mixed")[1]["content"]
    assert "SESSION LANGUAGE MODE" not in en  # en stays byte-identical to the pre-0024 prompt
    assert "SESSION LANGUAGE MODE: vn" in vn
    assert "SESSION LANGUAGE MODE: mixed" in mixed
    assert "language-invariant" in mixed.lower() or "language-invariant" in vn.lower()


def test_evaluate_threads_language_mode_into_the_prompt(make_client):
    client, fake = make_client([_eval_json(_good_dimensions())])
    evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric, language_mode="mixed")
    sent = fake.chat.completions.calls[0]["messages"][-1]["content"]
    assert "SESSION LANGUAGE MODE: mixed" in sent


def test_delivery_rubric_renders_the_separation_marker():
    rendered = _DELIVERY_RUBRIC.render()
    assert "english_delivery (assessed separately — NEVER counts toward weighted_score)" in rendered


@pytest.mark.live
def test_live_weak_scores_below_strong():
    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM primary provider not configured — set PRIMARY_PROVIDER and provider credentials")
    client = build_client(settings)
    strong = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    weak = evaluate(client, QUESTION.question, WEAK_ANSWER, QUESTION.rubric)
    assert set(strong.dimensions) == ACTIVE
    assert weak.weighted_score < strong.weighted_score
