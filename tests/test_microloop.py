from __future__ import annotations

import json
import logging

import pytest

from interview_coach.config import load_settings
from interview_coach.llm import build_client
from interview_coach.microloop import (
    DEFAULT_MAX_TURNS,
    CandidateExhausted,
    CandidateInputUnavailable,
    InteractiveCandidate,
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


def _tool(query: str = "L2 penalty variance mechanism") -> dict:
    return {
        "tool_calls": [
            {
                "name": "lookup_concept",
                "arguments": {
                    "query": query,
                    "skill": "ml_fundamentals",
                    "language": None,
                    "reason": "The candidate needs to explain the mechanism.",
                },
            }
        ]
    }


def _followup(
    question: str = "What mechanism connects the L2 penalty to lower variance?",
    targets: str = "penalty-to-variance mechanism",
) -> str:
    return json.dumps({"question": question, "targets": targets})


def _garbled_tool(name: str = "lookup_concpet") -> dict:
    # A garbled tool name (transient MiMo glitch) that the Interviewer cannot execute.
    return {
        "tool_calls": [
            {
                "name": name,
                "arguments": {"query": "x", "skill": "ml_fundamentals", "language": None, "reason": "r"},
            }
        ]
    }


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


def test_interactive_candidate_collects_multiline_answer():
    inputs = iter(["first line", "second line", ""])
    printed: list[str] = []
    candidate = InteractiveCandidate(input_func=lambda prompt: next(inputs), print_func=printed.append)

    answer = candidate.answer("Explain overfitting.")

    assert answer == "first line\nsecond line"
    assert printed[0] == "\nInterviewer:\nExplain overfitting.\n"
    assert "finish with a blank line" in printed[1]


def test_interactive_candidate_reports_eof_cleanly():
    def _eof(prompt: str) -> str:
        raise EOFError

    candidate = InteractiveCandidate(input_func=_eof, print_func=lambda text: None)

    with pytest.raises(CandidateInputUnavailable, match="run in a terminal"):
        candidate.answer("Question?")


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
            _tool(),
            _followup(question="What mechanism connects the L2 penalty to lower variance?"),
            _eval(4, follow_up=False),
        ]
    )
    seed = _seed(["weak answer", "a better answer"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert len(result.turns) == 2
    assert result.turns[0].is_follow_up is False
    assert result.turns[1].is_follow_up is True
    assert result.turns[1].question == "What mechanism connects the L2 penalty to lower variance?"
    assert result.turns[1].grounding_concept_id == "ml_fundamentals_l2_regularization"
    assert result.turns[0].trace.concept_lookup_query == "L2 penalty variance mechanism"
    assert result.turns[0].trace.concept_lookup_skill == "ml_fundamentals"
    assert result.turns[0].trace.concept_hit_id == "ml_fundamentals_l2_regularization"
    assert result.turns[1].trace.stop_reason is StopReason.RESOLVED
    assert result.turns[1].question != seed.question  # not a re-ask of the original
    assert result.turns[1].answer == "a better answer"  # the candidate answered the follow-up
    assert result.stop_reason is StopReason.RESOLVED
    assert fake.call_count == 4  # eval, native lookup tool call, follow-up, eval


def test_question_resolves_to_the_last_score(make_client):
    # The kept score is the LAST turn's (4), not the first weak one (2) — "keep the last score".
    client, _ = make_client(
        [_eval(2, follow_up=True), _tool(), _followup(), _eval(4, follow_up=False)]
    )
    seed = _seed(["weak", "better"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert result.resolved_evaluation is result.turns[-1].evaluation
    assert result.resolved_evaluation.weighted_score == pytest.approx(4.0)


def test_safety_cap_halts_pathological_loop_and_logs_a_guardrail_trip(make_client, caplog):
    # The Evaluator never stops flagging; the cap must halt the loop and log it as a guardrail trip
    # that is distinct from a normal resolution.
    client, fake = make_client(
        [_eval(2, follow_up=True), _tool(), _followup(), _eval(2, follow_up=True)]
    )
    seed = _seed(["a1", "a2"])
    with caplog.at_level(logging.INFO, logger="interview_coach.microloop"):
        result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=2)
    assert result.stop_reason is StopReason.SAFETY_CAP
    assert len(result.turns) == 2  # halted at the cap, not run away
    assert result.turns[-1].trace.stop_reason is StopReason.SAFETY_CAP
    assert fake.call_count == 4  # eval, native lookup tool call, follow-up, eval — then capped before a 3rd ask
    cap_logs = [r for r in caplog.records if "SAFETY CAP" in r.message]
    assert cap_logs and cap_logs[0].levelno == logging.WARNING  # a warning, not a routine info
    assert not any("resolved" in r.message for r in caplog.records)  # distinct from a normal stop


def test_micro_loop_degrades_when_follow_up_tool_call_stays_garbled(make_tool_client, caplog):
    # The Evaluator wants a follow-up but the Interviewer's tool name stays garbled past its retry.
    # One transient LLM glitch must not crash the question: the loop keeps the last score and resolves
    # with a distinct FOLLOW_UP_UNAVAILABLE stop reason (a degrade, not a normal resolution).
    client, fake = make_tool_client([_eval(2, follow_up=True), _garbled_tool()])
    seed = _seed(["a weak answer"])
    with caplog.at_level(logging.WARNING, logger="interview_coach.microloop"):
        result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=4)

    assert result.stop_reason is StopReason.FOLLOW_UP_UNAVAILABLE
    assert len(result.turns) == 1  # only the seed turn; the follow-up could not be generated
    assert result.turns[-1].trace.stop_reason is StopReason.FOLLOW_UP_UNAVAILABLE
    assert result.resolved_evaluation.weighted_score == pytest.approx(2.0)  # the last score is kept
    assert result.skill_state.mastery < 0.5  # the kept weak score still folds into the Skill state
    assert fake.call_count == 3  # eval + 2 garbled tool round-trips (one retry), then degrade
    assert any("could not obtain a follow-up" in r.message for r in caplog.records)


def test_cap_keeps_the_last_score_on_exit(make_client):
    client, _ = make_client([_eval(2, follow_up=True), _tool(), _followup(), _eval(2, follow_up=True)])
    seed = _seed(["a1", "a2"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=2)
    assert result.resolved_evaluation is result.turns[-1].evaluation
    assert result.skill_state.mastery < 0.5  # the kept weak score pulls mastery down


def test_micro_loop_does_not_override_evaluator_follow_up_decision(make_client):
    # ADR 0001 makes the Evaluator the single judge of whether a Follow-up is still useful. Even a
    # strong, confident follow-up answer must not be relabelled as resolved while the Evaluator flag
    # remains true; the Micro-loop can only stop by the safety cap in that case.
    client, fake = make_client(
        [
            _eval(3, follow_up=True),  # seed: a real gap -> probe once
            _tool(), _followup(), _eval(5, follow_up=True, confidence=0.9),  # FU1: strong + confident
            _tool(), _followup(), _eval(5, follow_up=True, confidence=0.9),  # FU2 -> cap
        ]
    )
    seed = _seed(["ok-ish", "strong fu1", "strong fu2"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=3)

    assert result.stop_reason is StopReason.SAFETY_CAP
    assert len(result.turns) == 3
    assert result.turns[-1].is_follow_up is True
    assert result.turns[-1].trace.stop_reason is StopReason.SAFETY_CAP
    assert fake.call_count == 7


def test_strong_seed_follow_up_still_runs_until_evaluator_resolves(make_client):
    # A strong seed the Evaluator wants to probe still earns its confirmatory Follow-up; resolution only
    # happens when the Evaluator lowers follow_up_recommended.
    client, fake = make_client(
        [
            _eval(5, follow_up=True, confidence=0.9),  # strong seed, but Evaluator still wants to probe
            _tool(), _followup(),
            _eval(5, follow_up=False, confidence=0.9),  # the follow-up answer resolves naturally
        ]
    )
    seed = _seed(["strong seed", "strong follow-up"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=4)

    assert len(result.turns) == 2
    assert result.turns[1].is_follow_up is True  # the first probe DID happen
    assert result.stop_reason is StopReason.RESOLVED


def test_weak_follow_up_reaches_cap_when_evaluator_keeps_flagging(make_client):
    # A weak follow-up answer is unresolved evidence, so the loop keeps probing to the cap.
    client, _ = make_client(
        [_eval(2, follow_up=True), _tool(), _followup(), _eval(2, follow_up=True, confidence=0.9)]
    )
    seed = _seed(["weak", "still weak"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers), max_turns=2)

    assert result.stop_reason is StopReason.SAFETY_CAP


def test_skill_state_is_updated_on_exit(make_client):
    # On loop exit the resolved score folds into the Skill state (slice 0002): mastery moves toward
    # the score and confidence rises off the neutral prior.
    client, _ = make_client([_eval(5, follow_up=False)])
    seed = _seed(["strong"])
    neutral = SkillState.neutral(seed.skill)
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert result.skill_state.mastery > neutral.mastery
    assert result.skill_state.confidence > neutral.confidence


def test_turn_trace_records_self_critique_trigger(make_client):
    # The Evaluator self-critique trace is copied onto the transcript turn so a Session can be
    # debugged without unpacking the raw Evaluation JSON.
    client, fake = make_client([_eval(3, follow_up=False, confidence=0.3), _eval(4, follow_up=False, confidence=0.9)])
    seed = _seed(["uncertain but sufficient"])
    result = run_micro_loop(client, seed, ScriptedCandidate(seed.answers))
    assert result.turns[0].trace.evaluator_self_critique_triggers == ("low_confidence",)
    assert result.turns[0].trace.stop_reason is StopReason.RESOLVED
    assert fake.call_count == 2


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
    result = run_micro_loop(
        client,
        seed,
        ScriptedCandidate(seed.answers),
        max_turns=len(seed.answers),
    )
    # If a follow-up was asked, it must be a genuinely new question, not the original restated.
    for turn in result.turns:
        if turn.is_follow_up:
            assert turn.question.strip() != seed.question.strip()
