from __future__ import annotations

import json

import pytest

from interview_coach.config import load_settings
from interview_coach.evaluator import Evaluation, evaluate
from interview_coach.fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from interview_coach.llm import build_client

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


def _eval_json(dimensions: dict, weighted: float = 4.0) -> str:
    return json.dumps(
        {
            "dimensions": dimensions,
            "weighted_score": weighted,
            "confidence": 0.8,
            "follow_up_recommended": False,
            "follow_up_rationale": "The answer is fully revealed.",
        }
    )


def test_evaluate_happy_path(make_client):
    client, fake = make_client([_eval_json(_good_dimensions())])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert isinstance(ev, Evaluation)
    assert set(ev.dimensions) == ACTIVE
    assert "mlops_awareness" not in ev.dimensions  # weight 0 -> not scored
    assert fake.call_count == 1


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


def test_no_evidence_is_allowed(make_client):
    dims = _good_dimensions()
    dims["system_thinking"] = {"score": 2, "evidence": "no evidence"}
    client, _ = make_client([_eval_json(dims)])
    ev = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    assert ev.dimensions["system_thinking"].evidence == "no evidence"


@pytest.mark.live
def test_live_weak_scores_below_strong():
    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM not configured — set LLM_API_KEY/BASE_URL/MODEL to run live tests")
    client = build_client(settings)
    strong = evaluate(client, QUESTION.question, STRONG_ANSWER, QUESTION.rubric)
    weak = evaluate(client, QUESTION.question, WEAK_ANSWER, QUESTION.rubric)
    assert set(strong.dimensions) == ACTIVE
    assert weak.weighted_score < strong.weighted_score
