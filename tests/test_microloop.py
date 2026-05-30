from __future__ import annotations

import json
import logging

import pytest

from interview_coach.config import load_settings
from interview_coach.llm import build_client
from interview_coach.microloop import (
    DEFAULT_MAX_TURNS,
    CandidateExhausted,
    ScriptedCandidate,
    StopReason,
    run_micro_loop,
)
from interview_coach.rubric import Rubric
from interview_coach.seeds import SEED_QUESTIONS
from interview_coach.skill import SkillState

# A single-dimension rubric keeps the scripted Evaluator replies tiny and focuses these tests on the
# loop's control flow rather than the Evaluator's internals (covered in test_evaluator.py).
_RUBRIC = Rubric(weights={"correctness": 1.0})


def _seed(answers, question="Explain the bias–variance tradeoff."):
    from interview_coach.seeds import SeedQuestion

    return SeedQuestion(skill="ml_fundamentals", question=question, rubric=_RUBRIC, answers=tuple(answers))


def _eval(score: int, *, follow_up: bool, confidence: float = 0.8) -> str:
    # weighted_score == the single dimension score, so the slice-0003 cross-check never trips here.
    return json.dumps(
        {
            "dimensions": {"correctness": {"score": score, "evidence": "no evidence"}},
            "weighted_score": float(score),
            "confidence": confidence,
            "follow_up_recommended": follow_up,
            "follow_up_rationale": "n/a",
        }
    )


def _followup(question: str = "What is the actual mechanism?", targets: str = "the gap") -> str:
    return json.dumps({"question": question, "targets": targets})


# --- ScriptedCandidate ------------------------------------------------------------------------


def test_scripted_candidate_replies_in_order():
    c = ScriptedCandidate(["first", "second"])
    assert c.answer("q1") == "first"
    assert c.answer("q2") == "second"


def test_scripted_candidate_raises_when_exhausted():
    c = ScriptedCandidate(["only"])
    assert c.answer("q1") == "only"
    with pytest.raises(CandidateExhausted):
        c.answer("q2")


def test_scripted_candidate_rejects_empty():
    with pytest.raises(ValueError):
        ScriptedCandidate([])


# --- micro-loop control flow ------------------------------------------------------------------


def test_strong_answer_resolves_without_follow_up(make_client):
    # Evaluator does not recommend a follow-up -> one turn, no Interviewer call, resolved normally.
    client, fake = make_client([_eval(5, follow_up=False)])
    result = run_micro_loop(client, _seed(["a strong answer"]), ScriptedCandidate(["a strong answer"]))
    assert len(result.turns) == 1
    assert result.turns[0].is_follow_up is False
    assert result.stop_reason is StopReason.RESOLVED
    assert fake.call_count == 1  # only the Evaluator ran; no follow-up was generated
    assert result.skill_state.mastery > 0.5  # a strong score lifts mastery


def test_weak_answer_triggers_follow_up_then_resolves(make_client):
    # Turn 1 (weak) flags a follow-up; the Interviewer asks one; turn 2 resolves.
    client, fake = make_client(
        [
            _eval(2, follow_up=True),
            _followup(question="Probe the missing mechanism?"),
            _eval(4, follow_up=False),
        ]
    )
    seed = _seed(["weak answer", "a better answer"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert len(result.turns) == 2
    assert result.turns[0].is_follow_up is False
    assert result.turns[1].is_follow_up is True
    assert result.turns[1].question == "Probe the missing mechanism?"  # the Interviewer-generated one
    assert result.turns[1].question != seed.question  # not a re-ask of the original
    assert result.turns[1].answer == "a better answer"  # the candidate answered the follow-up
    assert result.stop_reason is StopReason.RESOLVED
    assert fake.call_count == 3  # eval, follow-up, eval


def test_question_resolves_to_the_last_score(make_client):
    # The kept score is the LAST turn's (4), not the first weak one (2) — "keep the last score".
    client, _ = make_client(
        [_eval(2, follow_up=True), _followup(), _eval(4, follow_up=False)]
    )
    seed = _seed(["weak", "better"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert result.resolved_evaluation is result.turns[-1].evaluation
    assert result.resolved_evaluation.weighted_score == pytest.approx(4.0)


def test_safety_cap_halts_pathological_loop_and_logs_a_guardrail_trip(make_client, caplog):
    # The Evaluator never stops flagging; the cap must halt the loop and log it as a guardrail trip
    # that is distinct from a normal resolution.
    client, fake = make_client(
        [_eval(2, follow_up=True), _followup(), _eval(2, follow_up=True)]
    )
    seed = _seed(["a1", "a2"])
    with caplog.at_level(logging.INFO, logger="interview_coach.microloop"):
        result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=2)
    assert result.stop_reason is StopReason.SAFETY_CAP
    assert len(result.turns) == 2  # halted at the cap, not run away
    assert fake.call_count == 3  # eval, follow-up, eval — then capped before a 3rd ask
    cap_logs = [r for r in caplog.records if "SAFETY CAP" in r.message]
    assert cap_logs and cap_logs[0].levelno == logging.WARNING  # a warning, not a routine info
    assert not any("resolved" in r.message for r in caplog.records)  # distinct from a normal stop


def test_cap_keeps_the_last_score_on_exit(make_client):
    client, _ = make_client([_eval(2, follow_up=True), _followup(), _eval(2, follow_up=True)])
    seed = _seed(["a1", "a2"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=2)
    assert result.resolved_evaluation is result.turns[-1].evaluation
    assert result.skill_state.mastery < 0.5  # the kept weak score pulls mastery down


def test_skill_state_is_updated_on_exit(make_client):
    # On loop exit the resolved score folds into the Skill state (slice 0002): mastery moves toward
    # the score and confidence rises off the neutral prior.
    client, _ = make_client([_eval(5, follow_up=False)])
    seed = _seed(["strong"])
    neutral = SkillState.neutral(seed.skill)
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert result.skill_state.mastery > neutral.mastery
    assert result.skill_state.confidence > neutral.confidence


def test_incoming_skill_state_is_threaded(make_client):
    # A caller (the macro-loop, slice 0010) can pass an existing belief; the loop builds on it rather
    # than restarting from neutral.
    client, _ = make_client([_eval(5, follow_up=False)])
    seed = _seed(["strong"])
    prior = SkillState.neutral(seed.skill).observe(0.9)  # already some evidence
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), prior)
    assert result.skill_state.alpha + result.skill_state.beta > prior.alpha + prior.beta


def test_max_turns_must_be_positive(make_client):
    client, _ = make_client([_eval(5, follow_up=False)])
    seed = _seed(["x"])
    with pytest.raises(ValueError):
        run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=0)


def test_default_cap_is_one_question_plus_three_follow_ups():
    assert DEFAULT_MAX_TURNS == 4


# --- live (real provider) ---------------------------------------------------------------------


@pytest.mark.live
def test_live_strong_seed_resolves_high():
    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM primary provider not configured — set PRIMARY_PROVIDER and provider credentials")
    client = build_client(settings)
    seed = SEED_QUESTIONS[0]  # the strong opener
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert result.turns[0].is_follow_up is False
    assert result.turns[0].evaluation.weighted_score >= 4  # a genuinely strong answer scores high
    assert result.skill_state.mastery > 0.5


@pytest.mark.live
def test_live_follow_up_does_not_re_ask_the_question():
    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM primary provider not configured — set PRIMARY_PROVIDER and provider credentials")
    client = build_client(settings)
    seed = SEED_QUESTIONS[1]  # the weak opener, likely to draw a follow-up
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    # If a follow-up was asked, it must be a genuinely new question, not the original restated.
    for turn in result.turns:
        if turn.is_follow_up:
            assert turn.question.strip() != seed.question.strip()
