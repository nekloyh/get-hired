from __future__ import annotations

import json

from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.interviewer import FollowUp, generate_follow_up


def _followup_json(question: str = "What exactly makes the weights smaller, and why does that help?",
                   targets: str = "depth: the mechanism") -> str:
    return json.dumps({"question": question, "targets": targets})


def _weak_evaluation(rationale: str = "the answer never explains the mechanism") -> Evaluation:
    return Evaluation(
        dimensions={
            "correctness": DimensionScore(score=3, evidence="no evidence"),
            "depth": DimensionScore(score=2, evidence="it makes the weights smaller"),
        },
        weighted_score=2.5,
        confidence=0.7,
        follow_up_recommended=True,
        follow_up_rationale=rationale,
    )


def test_generate_follow_up_returns_structured(make_client):
    client, fake = make_client([_followup_json()])
    fu = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes the weights smaller which is better.",
        evaluation=_weak_evaluation(),
    )
    assert isinstance(fu, FollowUp)
    assert fu.question and fu.targets
    assert fake.call_count == 1


def test_follow_up_prompt_targets_the_gap(make_client):
    # The follow-up must target the gap, not re-ask the question — so the Interviewer is fed the
    # candidate's answer and the Evaluator's rationale + weak dimensions. Assert they reach the prompt.
    client, fake = make_client([_followup_json()])
    answer = "It makes the weights smaller which is better."
    generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer=answer,
        evaluation=_weak_evaluation(rationale="the answer never explains the mechanism"),
    )
    user_msg = fake.chat.completions.calls[0]["messages"][-1]["content"]
    assert answer in user_msg  # the Interviewer sees what was actually said...
    assert "the answer never explains the mechanism" in user_msg  # ...and where it fell short
    assert "depth: 2/5" in user_msg  # the weakest dimension is surfaced (weakest-first ordering)


def test_weakest_dimension_is_listed_first(make_client):
    client, fake = make_client([_followup_json()])
    generate_follow_up(
        client,
        original_question="q",
        answer="a",
        evaluation=_weak_evaluation(),
    )
    user_msg = fake.chat.completions.calls[0]["messages"][-1]["content"]
    # depth (2/5) must appear before correctness (3/5): the gap leads.
    assert user_msg.index("depth: 2/5") < user_msg.index("correctness: 3/5")


def test_generate_follow_up_rejects_reasking_original_question(make_client):
    # A follow-up that just restates the original question is answerable by repeating the original
    # answer — the acceptance criterion forbids it. The validator must reject it and retry.
    original = "Why does L2 regularization reduce overfitting?"
    client, fake = make_client(
        [
            _followup_json(question=original, targets="generic repeat"),
            _followup_json(
                question="What mechanism connects smaller weights to lower variance?",
                targets="depth: mechanism",
            ),
        ]
    )

    fu = generate_follow_up(
        client,
        original_question=original,
        answer="It makes weights smaller.",
        evaluation=_weak_evaluation(),
    )

    assert fu.question == "What mechanism connects smaller weights to lower variance?"
    assert fake.call_count == 2
