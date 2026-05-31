from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from interview_coach.diagnostic import CandidateProfile, diagnose
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.microloop import MicroLoopResult, StopReason, Turn
from interview_coach.rubric import Rubric
from interview_coach.seeds import SeedQuestion, seed_count
from interview_coach.skill import SkillState, apply_evaluation
from interview_coach.supervisor import (
    SessionStatus,
    SupervisorAction,
    build_session_graph,
    decide_next_move,
    export_architecture_diagram,
    initial_session_state,
    session_config,
)


def _decision(
    action: str,
    reasoning: str,
    *,
    target_skill: str | None = None,
    target_plan_index: int | None = None,
) -> str:
    return json.dumps(
        {
            "action": action,
            "reasoning": reasoning,
            "target_skill": target_skill,
            "target_plan_index": target_plan_index,
        }
    )


def _eval(score: int, *, follow_up: bool) -> str:
    return json.dumps(
        {
            "dimensions": {"correctness": {"score": score, "evidence": "no evidence"}},
            "weighted_score": float(score),
            "confidence": 0.8,
            "follow_up_recommended": follow_up,
            "follow_up_rationale": "needs more evidence",
        }
    )


_RESOURCE_FOR_SKILL = {
    "ml_fundamentals": "ml_fundamentals_cross_validation",
    "deep_learning": "deep_learning_resnet_d2l",
    "mlops": "mlops_google_rules",
    "system_design": "system_design_backpressure_rate_limiting",
    "vietnamese_nlp": "vietnamese_nlp_phobert",
}


def _plan(*skills: str) -> str:
    resource_ids = [_RESOURCE_FOR_SKILL[skill] for skill in skills]
    return json.dumps(
        {
            "readiness_estimate": 0.48,
            "readiness_rationale": "Several role-critical gaps still need focused practice.",
            "prioritized_topics": [
                {
                    "priority": i,
                    "skill": skill,
                    "title": f"Practice {skill}",
                    "rationale": "Final Skill state makes this a high-priority gap.",
                    "target_mastery": "Explain the core tradeoffs and handle a follow-up.",
                    "resource_ids": [_RESOURCE_FOR_SKILL[skill]],
                }
                for i, skill in enumerate(skills, start=1)
            ],
            "schedule": [
                {
                    "day": day,
                    "focus": f"Study day {day}",
                    "outcome": "Write a concise interview answer with one concrete tradeoff.",
                    "resource_ids": [resource_ids[(day - 1) % len(resource_ids)]],
                }
                for day in range(1, 15)
            ],
            "milestones": [
                {
                    "week": 1,
                    "description": "Answer the weakest Skill question without notes.",
                    "evidence": "A self-recorded answer covers the missing concepts.",
                },
                {
                    "week": 2,
                    "description": "Run a timed mixed mock interview.",
                    "evidence": "All planned Skills have a 3-minute answer and follow-up.",
                },
            ],
        }
    )


def _diagnostic():
    return diagnose(
        CandidateProfile(
            target_role="machine learning engineer",
            claimed_skills={"ml_fundamentals": 4, "mlops": 2},
            target_companies=("Viettel",),
        )
    )


def _fake_micro_loop(score: float):
    def _run(client, seed, candidate, state=None, *, max_turns=4, concept_store=None):
        before = state or SkillState.neutral(seed.skill)
        ev = Evaluation(
            dimensions={"correctness": DimensionScore(score=round(score), evidence="no evidence")},
            weighted_score=score,
            confidence=0.9,
            follow_up_recommended=False,
            follow_up_rationale="resolved",
        )
        return MicroLoopResult(
            skill=seed.skill,
            turns=(
                Turn(
                    question=seed.question,
                    answer=seed.answers[0],
                    evaluation=ev,
                    is_follow_up=False,
                ),
            ),
            stop_reason=StopReason.RESOLVED,
            skill_state=apply_evaluation(before, ev),
        )

    return _run


def test_strong_candidate_can_end_early_and_reasoning_is_logged(make_client, monkeypatch):
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(5.0))
    client, fake = make_client(
        [
            _decision("end_early", "Scores are consistently above the evidence bars."),
            _plan("system_design", "vietnamese_nlp", "ml_fundamentals"),
        ]
    )
    state = initial_session_state("strong-session", _diagnostic(), max_questions=5, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("strong-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert final["stop_reason"] == "supervisor_end_early"
    assert final["supervisor_decisions"][0]["action"] == "end_early"
    assert final["supervisor_decisions"][0]["deviation"] is True
    assert "consistently above" in final["supervisor_decisions"][0]["llm_reasoning"]
    assert final["study_plan"]["prioritized_topics"][0]["skill"] == "system_design"
    assert fake.call_count == 2


def test_struggling_candidate_can_trigger_extra_probe(make_client, monkeypatch):
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(2.0))
    client, fake = make_client(
        [
            _decision("extra_question", "Weak evidence needs one more probe."),
            _plan("mlops", "system_design", "vietnamese_nlp"),
        ]
    )
    state = initial_session_state("weak-session", _diagnostic(), max_questions=2, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("weak-session"))

    assert len(final["transcript"]) == 2
    assert final["stop_reason"] == "max_questions"
    assert final["supervisor_decisions"][0]["action"] == "extra_question"
    assert final["supervisor_decisions"][0]["deviation"] is True
    assert final["study_plan"]["prioritized_topics"][0]["skill"] == "mlops"
    assert fake.call_count == 2  # second Supervisor pass is deterministic; Planner is the second LLM call


def test_session_completes_when_study_planner_fails(make_client, monkeypatch):
    # The Study Plan is end-matter: a planner that returns an invalid plan past its retry must NOT
    # discard the fully-resolved interview. The Session completes with no plan + an error marker, so
    # one bad LLM response at the final node cannot sink the whole run.
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(5.0))
    client, fake = make_client(['{"bad": 1}', '{"bad": 1}'])  # planner invalid on both attempts
    state = initial_session_state("planner-fail-session", _diagnostic(), max_questions=1, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("planner-fail-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert final["stop_reason"] == "max_questions"
    assert len(final["transcript"]) == 1  # the resolved interview is preserved
    assert final["study_plan"] is None
    assert "StructuredOutputError" in final["study_plan_error"]
    assert fake.call_count == 2  # the two failed planner attempts; the hard cap means no Supervisor LLM call


def test_hard_question_cap_preempts_llm_choice(make_client, monkeypatch):
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(5.0))
    client, fake = make_client([_plan("system_design", "vietnamese_nlp", "ml_fundamentals")])
    state = initial_session_state("capped-session", _diagnostic(), max_questions=1, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("capped-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert final["stop_reason"] == "max_questions"
    assert final["supervisor_decisions"][0]["action"] == "end_early"
    assert "Hard cap reached" in final["supervisor_decisions"][0]["llm_reasoning"]
    assert final["study_plan"]["prioritized_topics"][0]["skill"] == "system_design"
    assert fake.call_count == 1


def test_session_caps_micro_loop_to_scripted_seed_answers(make_client, monkeypatch):
    from interview_coach import supervisor

    one_answer_seed = SeedQuestion(
        skill="ml_fundamentals",
        question="One-answer fixture question?",
        rubric=Rubric(weights={"correctness": 1.0}),
        answers=("partial answer",),
    )
    monkeypatch.setattr(supervisor, "select_seed_question", lambda skill, question_number=0: one_answer_seed)
    client, fake = make_client([_eval(2, follow_up=True), _plan("mlops", "system_design", "vietnamese_nlp")])
    state = initial_session_state("one-answer-session", _diagnostic(), max_questions=1, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("one-answer-session"))

    assert final["transcript"][0]["stop_reason"] == StopReason.SAFETY_CAP.value
    assert fake.call_count == 2  # Evaluator + Planner; no Follow-up generation because the seed has no answer


def test_session_resumes_from_sqlite_checkpoint_by_session_id(tmp_path, make_client, monkeypatch):
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(4.0))
    db_path = tmp_path / "session.sqlite"
    session_id = "resume-session"
    state = initial_session_state(session_id, _diagnostic(), max_questions=3, started_at=0)

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        first_client, _ = make_client([_decision("advance_plan", "Need the next planned Skill.")])
        graph = build_session_graph(first_client, checkpointer=checkpointer, now=lambda: 1)
        partial = graph.invoke(state, session_config(session_id), interrupt_after=["run_question"])
        snapshot = graph.get_state(session_config(session_id))

    assert len(partial["transcript"]) == 1
    assert snapshot.next == ("supervisor",)

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        second_client, _ = make_client(
            [
                _decision("advance_plan", "Need the next planned Skill."),
                _decision("end_early", "Enough evidence after resume."),
                _plan("mlops", "system_design", "vietnamese_nlp"),
            ]
        )
        resumed_graph = build_session_graph(second_client, checkpointer=checkpointer, now=lambda: 1)
        final = resumed_graph.invoke(None, session_config(session_id))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert len(final["transcript"]) == 2
    assert final["supervisor_decisions"][-1]["action"] == "end_early"


def test_architecture_diagram_exports_png(tmp_path, make_client):
    client, _ = make_client([_decision("end_early", "not used")])
    output = export_architecture_diagram(tmp_path / "architecture.png", client)

    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


# --- seed gate: a deviation must not re-probe a Skill with no unused seed -----------------------


def _transcript_item(skill: str, *, score: float = 3.0) -> dict:
    return {
        "skill": skill,
        "plan_index": 0,
        "stop_reason": "resolved",
        "resolved_weighted_score": score,
        "resolved_confidence": 0.7,
        "skill_state": {"skill": skill, "alpha": 1.0, "beta": 1.0},
        "turns": [],
    }


def _state_with_transcript(probed: list[str]):
    state = initial_session_state("gate-session", _diagnostic(), max_questions=10, started_at=0)
    state["transcript"] = [_transcript_item(skill) for skill in probed]
    state["question_count"] = len(probed)
    return state


def test_seed_count_matches_bank():
    assert seed_count("ml_fundamentals") == 3
    for skill in ("deep_learning", "mlops", "system_design", "vietnamese_nlp"):
        assert seed_count(skill) >= 2


def test_extra_question_gated_then_supervisor_advances(make_client):
    # mlops has been probed for all of its seeds, so extra_question must be rejected and the model
    # is steered to advance_plan on retry.
    state = _state_with_transcript(["mlops"] * seed_count("mlops"))
    client, fake = make_client(
        [
            _decision("extra_question", "I want one more mlops probe."),
            _decision("advance_plan", "No mlops seeds remain; advancing."),
        ]
    )
    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.ADVANCE_PLAN
    assert fake.call_count == 2  # first choice rejected by the seed gate, second accepted


def test_extra_question_allowed_when_a_seed_remains(make_client):
    # Only one mlops seed used; an unused one remains, so the gate permits extra_question.
    state = _state_with_transcript(["mlops"])
    client, fake = make_client([_decision("extra_question", "Weak mlops evidence; one more probe.")])
    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.EXTRA_QUESTION
    assert fake.call_count == 1


def test_switch_skill_gated_to_exhausted_target(make_client):
    # The Candidate has been probed on every mlops seed; switching back to mlops is rejected.
    state = _state_with_transcript(["ml_fundamentals", *(["mlops"] * seed_count("mlops"))])
    client, fake = make_client(
        [
            _decision("switch_skill", "Revisit mlops.", target_skill="mlops"),
            _decision("advance_plan", "mlops is exhausted; advancing instead."),
        ]
    )
    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.ADVANCE_PLAN
    assert fake.call_count == 2


# --- live (real provider) ---------------------------------------------------------------------


@pytest.mark.live
def test_live_session_runs_through_graph_and_logs_supervisor_reasoning():
    from interview_coach.config import load_settings
    from interview_coach.llm import build_client

    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM primary provider not configured — set PRIMARY_PROVIDER and provider credentials")
    client = build_client(settings)
    state = initial_session_state("live-audit-session", _diagnostic(), max_questions=2)

    graph = build_session_graph(client)
    final = graph.invoke(state, session_config("live-audit-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert 1 <= len(final["transcript"]) <= 2
    assert final["supervisor_decisions"], "the Supervisor should log at least one decision"
    assert all(d["llm_reasoning"].strip() for d in final["supervisor_decisions"])
