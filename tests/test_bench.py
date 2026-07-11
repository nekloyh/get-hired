from __future__ import annotations

import json

import pytest

from interview_coach.bench import (
    BenchCase,
    BenchResult,
    bench_passed,
    confidence_calibration,
    dimension_bias,
    language_deltas,
    load_bench_data,
    render_bench_report,
    run_bench,
    weak_strong_separation,
)
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.rubric import Rubric


def _case(case_id, *, paired_id="p", language="en", skill="ml_fundamentals", labels=None, lo=1.0, hi=5.0):
    return BenchCase(
        case_id=case_id,
        paired_id=paired_id,
        skill=skill,
        language=language,
        question="q?",
        answer="a",
        rubric=Rubric(weights={"correctness": 1.0}),
        labels=labels or {"correctness": 3},
        expected_min=lo,
        expected_max=hi,
    )


def _result(case, *, dims=None, weighted, confidence=0.8):
    evaluation = Evaluation(
        dimensions={d: DimensionScore(score=s, evidence="no evidence") for d, s in (dims or {}).items()},
        weighted_score=weighted,
        confidence=confidence,
        follow_up_recommended=False,
        follow_up_rationale="resolved",
    )
    return BenchResult(case=case, evaluation=evaluation)


def _eval_json(score: int, dims: dict[str, int], confidence: float = 0.8) -> str:
    return json.dumps(
        {
            "dimensions": {d: {"score": s, "evidence": "no evidence"} for d, s in dims.items()},
            "weighted_score": float(score),
            "confidence": confidence,
            "follow_up_recommended": False,
            "follow_up_rationale": "resolved",
        }
    )


# --- dataset ------------------------------------------------------------------------------------


def test_bench_dataset_is_bilingual_and_covers_multiple_skills():
    data = load_bench_data()
    assert len(data.cases) >= 20
    assert {c.language for c in data.cases} == {"en", "vi", "mixed"}
    assert len({c.skill for c in data.cases}) >= 2
    # a multi-case pair touching en/vi must be a complete en+vi twin set; single-case entries
    # (mixed-mode and en-solo delivery-coverage cases, 0024/0027) legitimately stand alone
    from collections import Counter

    pair_cases: dict[str, list] = {}
    for c in data.cases:
        pair_cases.setdefault(c.paired_id, []).append(c)
    for cases in pair_cases.values():
        langs = {c.language for c in cases}
        if len(cases) > 1 and langs & {"en", "vi"}:
            assert langs == {"en", "vi"}
    # BARS anchors for >= 2 dimensions, each with a 2 and a 4 exemplar
    assert len(data.anchors) >= 2
    assert all({"2", "4"} <= set(bands) for bands in data.anchors.values())
    # the prompt-injection adversarial case is retained with a VN twin
    assert Counter(c.paired_id for c in data.cases)["prompt_injection"] == 2


def test_bench_dataset_mixed_mode_cases_are_wired_for_0024():
    """Mixed-mode cases (issue 0024): language_mode threads to the judge, delivery only on EN answers."""
    from interview_coach.language import answer_is_english

    data = load_bench_data()
    mixed = [c for c in data.cases if c.language == "mixed"]
    assert len(mixed) >= 4
    assert all(c.language_mode == "mixed" for c in mixed)
    # legacy en/vi cases keep byte-stable prompts: no language_mode override
    assert all(c.language_mode == "en" for c in data.cases if c.language != "mixed")
    # the delivery dimension is active exactly on the English-dominant answers
    for c in mixed:
        active = c.rubric.weights.get("english_delivery", 0.0) > 0
        assert active == answer_is_english(c.answer)
        if active:
            assert "english_delivery" in c.labels
    # english_delivery has a BARS anchor now that it is labelled
    assert "english_delivery" in data.anchors
    # at least one case proves disentanglement: weak delivery label on a technically-strong band
    assert any(
        c.labels.get("english_delivery", 5) <= 2 and c.expected_min >= 3.0
        for c in mixed
    )


# --- pure metrics -------------------------------------------------------------------------------


def test_dimension_bias_is_signed_judge_minus_human():
    results = [
        _result(_case("a", labels={"correctness": 3}), dims={"correctness": 5}, weighted=5),  # +2
        _result(_case("b", labels={"correctness": 4}), dims={"correctness": 3}, weighted=3),  # -1
    ]
    bias = dimension_bias(results)
    assert bias["correctness"]["bias"] == 0.5  # mean(+2, -1)
    assert bias["correctness"]["n"] == 2


def test_weak_strong_separation():
    results = [
        _result(_case("weak", lo=1.0, hi=2.0), weighted=1.5),
        _result(_case("strong", lo=3.5, hi=5.0), weighted=4.5),
    ]
    sep = weak_strong_separation(results)
    assert sep["mean_weak"] == 1.5
    assert sep["mean_strong"] == 4.5
    assert sep["gap"] == 3.0


def test_language_deltas_pair_en_and_vi():
    results = [
        _result(_case("en", paired_id="x", language="en"), weighted=4.0),
        _result(_case("vi", paired_id="x", language="vi"), weighted=3.4),
    ]
    rows = language_deltas(results)
    assert len(rows) == 1
    assert rows[0]["paired_id"] == "x"
    assert rows[0]["en"] == 4.0
    assert rows[0]["vi"] == 3.4
    assert rows[0]["delta"] == pytest.approx(0.6)


def test_confidence_calibration_buckets_by_confidence():
    results = [
        _result(_case("hit", lo=3.0, hi=5.0), weighted=4.0, confidence=0.9),  # in band
        _result(_case("miss", lo=1.0, hi=2.0), weighted=4.0, confidence=0.95),  # out of band
    ]
    rows = confidence_calibration(results)
    top = [r for r in rows if r["bucket"].startswith("[0.9")][0]
    assert top["n"] == 2
    assert top["hit_rate"] == 0.5  # one of two landed in band despite high confidence


# --- report + gate ------------------------------------------------------------------------------


def test_report_has_every_section():
    en_case = _case("en", paired_id="x", language="en", labels={"correctness": 4})
    vi_case = _case("vi", paired_id="x", language="vi", labels={"correctness": 4})
    results = [
        _result(en_case, dims={"correctness": 4}, weighted=4.0, confidence=0.9),
        _result(vi_case, dims={"correctness": 3}, weighted=3.2, confidence=0.6),
    ]
    report = render_bench_report(
        results,
        anchors={"correctness": {"2": "half right", "4": "accurate"}},
        provider="openai",
        model="gpt-4o-mini",
        date="2026-07-07",
    )
    for section in [
        "# Judge Calibration Bench",
        "Per-dimension bias",
        "Weak/strong separation",
        "EN vs VN paired deltas",
        "Confidence calibration",
        "BARS anchors",
        "openai",
    ]:
        assert section in report


def test_run_bench_gate_passes_within_band_and_fails_on_regression(make_client):
    cases = (
        _case("ok", labels={"correctness": 4}, lo=3.0, hi=5.0),
        _case("regressed", labels={"correctness": 1}, lo=1.0, hi=2.5),
    )
    # The judge scores both a 4 — fine for the first, a regression for the second (band tops at 2.5).
    client, fake = make_client([_eval_json(4, {"correctness": 4}), _eval_json(4, {"correctness": 4})])
    results = run_bench(client, cases)
    assert results[0].within_band
    assert not results[1].within_band
    assert not bench_passed(results)
    assert fake.call_count == 2


def test_run_bench_marks_provider_error_as_out_of_band(make_client):
    client, _ = make_client(['{"bad": 1}', '{"bad": 1}'])
    results = run_bench(client, (_case("broken"),))
    assert results[0].error is not None
    assert not results[0].within_band
    assert not bench_passed(results)


def test_empty_bench_does_not_pass_the_gate_vacuously():
    # all([]) is True, so a malformed/empty cases.yaml (zero results) must not wave the gate through
    # green — a bench that evaluated nothing has not passed.
    assert not bench_passed([])


# --- english_delivery gate (issue 0024) ----------------------------------------------------------


def _delivery_case(label: int | None):
    labels = {"correctness": 4}
    weights = {"correctness": 1.0}
    if label is not None:
        labels["english_delivery"] = label
        weights["english_delivery"] = 0.0  # assessed separately, excluded from weighted_score
    return BenchCase(
        case_id="delivery",
        paired_id="delivery",
        skill="ml_fundamentals",
        language="mixed",
        question="q?",
        answer="a",
        rubric=Rubric(weights=weights),
        labels=labels,
        expected_min=3.0,
        expected_max=5.0,
        language_mode="mixed",
    )


def test_delivery_within_band_is_vacuous_without_a_label():
    result = _result(_delivery_case(None), dims={"correctness": 4}, weighted=4.0)
    assert result.delivery_within_band


def test_delivery_within_band_tolerates_one_point_and_rejects_two():
    case = _delivery_case(2)
    near = _result(case, dims={"correctness": 4, "english_delivery": 3}, weighted=4.0)
    assert near.delivery_within_band
    far = _result(case, dims={"correctness": 4, "english_delivery": 4}, weighted=4.0)
    assert not far.delivery_within_band


def test_delivery_within_band_fails_when_labelled_but_unjudged_or_errored():
    case = _delivery_case(2)
    # judgment skipped the dimension entirely
    skipped = _result(case, dims={"correctness": 4}, weighted=4.0)
    assert not skipped.delivery_within_band
    # the case errored — a labelled dimension that never got judged cannot pass
    errored = BenchResult(case=case, error="StructuredOutputError: boom")
    assert not errored.delivery_within_band


def test_delivery_miss_fails_the_gate_even_inside_the_technical_band():
    # The whole point of the second gate: english_delivery is excluded from weighted_score, so a
    # coin-flip delivery judge would sail through within_band without this check.
    case = _delivery_case(2)
    result = _result(case, dims={"correctness": 4, "english_delivery": 5}, weighted=4.0)
    assert result.within_band
    assert not bench_passed([result])
