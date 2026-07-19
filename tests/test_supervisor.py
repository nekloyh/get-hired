from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from interview_coach.diagnostic import CandidateProfile, diagnose
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.microloop import MicroLoopResult, ScriptedCandidate, StopReason, Turn
from interview_coach.rubric import Rubric
from interview_coach.seeds import SeedQuestion, SeedQuestionsExhausted, seed_count
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
    # english_delivery rides along because the en-mode loop activates it on English answers (0024).
    return json.dumps(
        {
            "dimensions": {
                "correctness": {"score": score, "evidence": "no evidence"},
                "english_delivery": {"score": 4, "evidence": "no evidence"},
            },
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
    def _run(
        client,
        seed,
        candidate,
        state=None,
        *,
        max_turns=4,
        concept_store=None,
        language_mode="en",
        interviewer_client=None,
    ):
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


def _failing_then_resolving_micro_loop(score: float, *, fail_times: int = 1):
    """A micro-loop stub that raises on the first ``fail_times`` questions, then resolves normally."""
    base = _fake_micro_loop(score)
    calls = {"n": 0}

    def _run(
        client,
        seed,
        candidate,
        state=None,
        *,
        max_turns=4,
        concept_store=None,
        language_mode="en",
        interviewer_client=None,
    ):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise RuntimeError("evaluator blew up on this question")
        return base(client, seed, candidate, state, max_turns=max_turns, concept_store=concept_store)

    return _run


def test_question_failure_is_isolated_and_session_continues(make_client, monkeypatch):
    # A crash inside one question (here the Evaluator/micro-loop raises) must NOT abort the whole
    # multi-question Session (slice 0014): the question is recorded as `failed`, the Skill belief is
    # left untouched, the Supervisor advances, and questions resolved afterwards are preserved.
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _failing_then_resolving_micro_loop(5.0, fail_times=1))
    client, fake = make_client(
        [
            _decision("advance_plan", "The first question could not be scored; move to the next planned Skill."),
            _plan("mlops", "system_design", "vietnamese_nlp"),
        ]
    )
    state = initial_session_state("failure-isolation-session", _diagnostic(), max_questions=2, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("failure-isolation-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert len(final["transcript"]) == 2  # the failed question and the later resolved one are both kept

    failed = final["transcript"][0]
    assert failed["stop_reason"] == StopReason.FAILED.value
    assert failed["turns"] == []
    assert "RuntimeError" in failed["error"]  # the failure is recorded, not silently swallowed
    # a failed question is not evidence of low mastery: the Skill belief is the unchanged prior
    assert final["skill_states"][failed["skill"]] == failed["skill_state"]

    resolved = final["transcript"][1]
    assert resolved["stop_reason"] == StopReason.RESOLVED.value

    assert final["question_count"] == 2
    assert final["study_plan"] is not None  # the run completed and still produced a plan
    assert fake.call_count == 2  # one Supervisor advance after the failure + the Planner


def test_language_mode_threads_from_state_into_the_micro_loop(make_client, monkeypatch):
    # Issue 0024: the mode chosen at setup rides the SessionState into every run_micro_loop call.
    from interview_coach import supervisor

    seen: list[str] = []
    base = _fake_micro_loop(4.0)

    def _capture(
        client,
        seed,
        candidate,
        state=None,
        *,
        max_turns=4,
        concept_store=None,
        language_mode="en",
        interviewer_client=None,
    ):
        seen.append(language_mode)
        return base(client, seed, candidate, state, max_turns=max_turns, concept_store=concept_store)

    monkeypatch.setattr(supervisor, "run_micro_loop", _capture)
    client, _ = make_client(
        [
            _decision("end_early", "Evidence is decisive after one question; end the session."),
            _plan("mlops", "system_design", "vietnamese_nlp"),
        ]
    )
    state = initial_session_state(
        "language-thread-session", _diagnostic(), max_questions=1, started_at=0, language_mode="mixed"
    )
    assert state["language_mode"] == "mixed"

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("language-thread-session"))

    assert seen == ["mixed"]
    assert final["language_mode"] == "mixed"  # survives to the final state for export/web


def test_initial_session_state_rejects_unknown_language_mode():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="unknown language_mode"):
        initial_session_state("bad-mode", _diagnostic(), language_mode="vi")


def test_candidate_intent_aborts_session_and_is_not_recorded_as_failed(make_client):
    # ADR 0005 / issue 0018: a Candidate-intent signal (EOF/Ctrl-D, a web cancel/disconnect) must
    # propagate OUT of the per-question failure-isolation net — it aborts the Session and is never
    # converted into a zero-evidence `failed` question. This is the opposite of an infrastructure
    # failure (see test_question_failure_is_isolated_and_session_continues, which records + advances).
    from interview_coach.microloop import CandidateInputUnavailable

    class _AbortingCandidate:
        def answer(self, question: str) -> str:
            raise CandidateInputUnavailable("interactive Candidate input ended before an answer")

    client, fake = make_client([_eval(5, follow_up=False)])
    state = initial_session_state("intent-abort-session", _diagnostic(), max_questions=3, started_at=0)
    graph = build_session_graph(
        client, candidate_factory=lambda seed: _AbortingCandidate(), max_turns_per_question=1, now=lambda: 1
    )

    with pytest.raises(CandidateInputUnavailable):
        graph.invoke(state, session_config("intent-abort-session"))

    # The Candidate aborted before the Evaluator ran, so no LLM call and no failed question was recorded.
    assert fake.call_count == 0


def test_supervisor_degrades_on_transport_error_at_decision_node(make_client, monkeypatch):
    # Issue 0020: a provider/transport error at the Supervisor's decision node (the only otherwise
    # unguarded macro-loop LLM call) must degrade to the deterministic plan-following decision, not
    # crash the Session — mirroring question_node/study_plan_node. Recorded distinctly from a schema
    # fallback so the export shows the degrade honestly.
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(4.0))
    client, _ = make_client(
        [
            ConnectionError("provider timed out after fallback exhaustion"),  # supervisor decision call
            _plan("mlops", "system_design", "vietnamese_nlp"),  # the Study Plan still runs at the end
        ]
    )
    state = initial_session_state("transport-degrade-session", _diagnostic(), max_questions=2, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("transport-degrade-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert len(final["transcript"]) == 2  # the Session continued past the transport error, did not crash
    reasons = [d["llm_reasoning"] for d in final["supervisor_decisions"]]
    assert any("transport error" in reason for reason in reasons)  # the degrade is recorded honestly


def test_max_elapsed_seconds_hard_rail_ends_session(make_client):
    # Issue 0019 gave the elapsed-time rail its first test: a clock past the budget ends the Session
    # deterministically, before any Supervisor LLM deviation choice.
    state = initial_session_state(
        "elapsed-session", _diagnostic(), max_questions=10, max_elapsed_seconds=100, started_at=0
    )
    state["transcript"] = [_transcript_item("mlops")]
    state["question_count"] = 1
    client, fake = make_client([])  # the hard rail preempts the LLM, so no reply is needed

    decision = decide_next_move(client, state, now=lambda: 10_000)

    assert decision.action is SupervisorAction.END_EARLY
    assert "max_elapsed_seconds" in decision.reasoning
    assert fake.call_count == 0


def test_resumable_session_state_returns_none_for_unknown_id(tmp_path, make_client):
    from interview_coach.supervisor import resumable_session_state

    client, _ = make_client([])
    with SqliteSaver.from_conn_string(str(tmp_path / "session.sqlite")) as checkpointer:
        graph = build_session_graph(client, checkpointer=checkpointer, now=lambda: 1)
        assert resumable_session_state(graph, "never-started") is None


def test_resume_resets_elapsed_clock_so_a_long_gap_does_not_force_complete(tmp_path, make_client, monkeypatch):
    # Issue 0019: max_elapsed_seconds measured wall-clock since creation, so resuming a day later
    # force-completed after one question. Resetting started_at on resume restarts the sitting's budget
    # so the Session continues instead.
    from interview_coach import supervisor

    monkeypatch.setattr(supervisor, "run_micro_loop", _fake_micro_loop(4.0))
    db_path = str(tmp_path / "session.sqlite")
    session_id = "gap-session"
    state = initial_session_state(session_id, _diagnostic(), max_questions=3, max_elapsed_seconds=100, started_at=0)

    # First sitting: resolve one question, then suspend before the Supervisor decides.
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        first_client, _ = make_client([_decision("advance_plan", "next planned Skill")])
        graph = build_session_graph(first_client, checkpointer=checkpointer, now=lambda: 1)
        partial = graph.invoke(state, session_config(session_id), interrupt_after=["run_question"])
    assert len(partial["transcript"]) == 1

    # Resume "a day later": a clock far past the budget (now=10_000, started_at=0) WOULD trip the
    # elapsed rail immediately if the budget still measured time since creation. Resetting started_at
    # to now restarts the budget, so the Session continues past the gap.
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        second_client, _ = make_client(
            [
                _decision("advance_plan", "continue after the gap"),
                _decision("end_early", "enough evidence after the gap"),
                _plan("mlops", "system_design", "vietnamese_nlp"),
            ]
        )
        resumed_graph = build_session_graph(second_client, checkpointer=checkpointer, now=lambda: 10_000)
        resumed_graph.update_state(session_config(session_id), {"started_at": 10_000.0})
        final = resumed_graph.invoke(None, session_config(session_id))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert len(final["transcript"]) >= 2  # continued past the gap, not force-completed after one question


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
        answers=("a partial answer missing the mechanism",),
    )
    monkeypatch.setattr(supervisor, "select_seed_question", lambda skill, question_number=0, **kwargs: one_answer_seed)
    client, fake = make_client([_eval(2, follow_up=True), _plan("mlops", "system_design", "vietnamese_nlp")])
    state = initial_session_state("one-answer-session", _diagnostic(), max_questions=1, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("one-answer-session"))

    assert final["transcript"][0]["stop_reason"] == StopReason.SAFETY_CAP.value
    assert fake.call_count == 2  # Evaluator + Planner; no Follow-up generation because the seed has no answer


def test_session_can_use_candidate_factory_for_interactive_answers(make_client, monkeypatch):
    from interview_coach import supervisor

    seed = SeedQuestion(
        skill="ml_fundamentals",
        question="Factory question?",
        rubric=Rubric(weights={"correctness": 1.0}),
        answers=("a scripted answer naming the mechanism",),
    )
    monkeypatch.setattr(supervisor, "select_seed_question", lambda skill, question_number=0, **kwargs: seed)
    client, _ = make_client([_eval(5, follow_up=False), _plan("system_design", "vietnamese_nlp", "ml_fundamentals")])
    state = initial_session_state("factory-session", _diagnostic(), max_questions=1, started_at=0)

    graph = build_session_graph(
        client,
        candidate_factory=lambda active_seed: ScriptedCandidate(["a factory answer naming the mechanism"]),
        max_turns_per_question=1,
        now=lambda: 1,
    )
    final = graph.invoke(state, session_config("factory-session"))

    assert final["transcript"][0]["turns"][0]["question"] == "Factory question?"
    assert final["transcript"][0]["turns"][0]["answer"] == "a factory answer naming the mechanism"


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


def _transcript_item(skill: str, *, score: float = 3.0, stop_reason: str = "resolved") -> dict:
    return {
        "skill": skill,
        "plan_index": 0,
        "stop_reason": stop_reason,
        "resolved_weighted_score": score,
        "resolved_confidence": 0.7,
        "skill_state": {"skill": skill, "alpha": 1.0, "beta": 1.0},
        "turns": [],
    }


def _state_with_transcript(probed: list[str]):
    # max_questions sits above the largest per-Skill seed count so the exhaustion gates below are
    # what fires, not the session-length stop.
    state = initial_session_state("gate-session", _diagnostic(), max_questions=40, started_at=0)
    state["transcript"] = [_transcript_item(skill) for skill in probed]
    state["question_count"] = len(probed)
    return state


def test_seed_count_matches_bank():
    assert seed_count("ml_fundamentals") == 9
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


def test_seed_exhaustion_is_isolated_as_a_failed_question_not_a_duplicate(make_client, monkeypatch):
    # Backstop for issue 0032: an over-subscribed plan (unreachable via the diagnostic validator, but
    # guarded) makes select_seed_question raise SeedQuestionsExhausted. The question_node
    # failure-isolation net must record it as a visible FAILED question and let the Session complete —
    # never re-serve a duplicate prompt or abort the run.
    from interview_coach import supervisor

    def _raise_exhausted(skill, question_number=0, **kwargs):
        raise SeedQuestionsExhausted(skill, question_number, seed_count(skill))

    monkeypatch.setattr(supervisor, "select_seed_question", _raise_exhausted)
    client, _ = make_client([_plan("mlops", "system_design", "vietnamese_nlp")])
    state = initial_session_state("exhausted-session", _diagnostic(), max_questions=1, started_at=0)

    graph = build_session_graph(client, now=lambda: 1)
    final = graph.invoke(state, session_config("exhausted-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert len(final["transcript"]) == 1  # one slot, recorded once — not a wrapped duplicate
    assert final["transcript"][0]["stop_reason"] == StopReason.FAILED.value
    assert "SeedQuestionsExhausted" in final["transcript"][0]["error"]


def test_safety_cap_below_evidence_bar_requires_extra_question_when_seed_remains(make_client):
    state = initial_session_state("safety-cap-session", _diagnostic(), max_questions=10, started_at=0)
    state["transcript"] = [_transcript_item("mlops", score=3.0, stop_reason=StopReason.SAFETY_CAP.value)]
    state["question_count"] = 1
    client, fake = make_client(
        [
            _decision("advance_plan", "Move on despite the unresolved mlops evidence."),
            _decision("extra_question", "The safety cap left mlops unresolved and one seed remains."),
        ]
    )

    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.EXTRA_QUESTION
    assert fake.call_count == 2


def test_advance_plan_rejects_reasoning_that_claims_same_skill_probe(make_client):
    state = initial_session_state("reasoning-session", _diagnostic(), max_questions=10, started_at=0)
    state["transcript"] = [_transcript_item("mlops", score=4.0)]
    state["question_count"] = 1
    client, fake = make_client(
        [
            _decision("advance_plan", "Advance plan so we can ask another mlops question for more evidence."),
            _decision("advance_plan", "Move to the next planned Skill."),
        ]
    )

    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.ADVANCE_PLAN
    assert decision.reasoning == "Move to the next planned Skill."
    assert fake.call_count == 2


def test_advance_plan_allows_reasoning_that_says_skill_was_already_probed(make_client):
    state = initial_session_state("already-probed-session", _diagnostic(), max_questions=10, started_at=0)
    state["transcript"] = [_transcript_item("mlops", score=4.0)]
    state["question_count"] = 1
    client, fake = make_client(
        [_decision("advance_plan", "mlops was already probed, so move to the next planned Skill.")]
    )

    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.ADVANCE_PLAN
    assert fake.call_count == 1


def test_supervisor_uses_deterministic_fallback_after_repeated_invalid_reasoning(make_client):
    state = initial_session_state("fallback-session", _diagnostic(), max_questions=10, started_at=0)
    state["transcript"] = [_transcript_item("mlops", score=4.0)]
    state["question_count"] = 1
    client, fake = make_client(
        [
            _decision("advance_plan", "Advance plan so we can ask another mlops question for more evidence."),
            _decision("advance_plan", "Still ask another mlops question for more evidence."),
        ]
    )

    decision = decide_next_move(client, state, now=lambda: 1)

    assert decision.action is SupervisorAction.ADVANCE_PLAN
    assert decision.reasoning == "Deterministic fallback: move to the next Topic Plan entry."
    assert fake.call_count == 2


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
