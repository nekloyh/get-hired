from __future__ import annotations

import json
import re
from collections.abc import Sequence

from interview_coach.llm import LLMClient, Message, ResponseFormat
from interview_coach.replay import (
    REPLAY_ARTIFACT_VERSION,
    Persona,
    PersonaCandidate,
    attempts_by_skill,
    dump_replay_artifact,
    ground_truth_ordering,
    load_replay_artifact,
    posterior_masteries,
    probed_ordering,
    replay_decision,
    run_persona_session,
)
from interview_coach.rubric import DIMENSIONS
from interview_coach.supervisor import SessionStatus


class _PersonaTextClient(LLMClient):
    """A stand-in for the persona's answer generator: echoes the level word from its system prompt."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, messages: Sequence[Message], *, response_format: ResponseFormat | None = None,
             disable_thinking: bool = False) -> str:
        text = " ".join(m["content"] for m in messages)
        self.calls.append(text)
        # The persona's true level appears as "ability on this topic (<skill>) is <level>".
        match = re.search(r"ability on this topic \(\w+\) is (\w+)", text)
        return f"A {match.group(1)} answer." if match else "An answer."


class _SimJudge(LLMClient):
    """A content-based judge: scores an answer from its level marker, so the loop closes on the persona.

    Returns a valid Evaluation for any Evaluator prompt (including self-critique — no queue to misalign)
    and a fixed decision for any Supervisor prompt. This makes the trajectory emergent from the
    persona's answers rather than a scripted score sequence.
    """

    def __init__(self, *, supervisor_action: str = "advance_plan") -> None:
        self.supervisor_action = supervisor_action

    def chat(self, messages: Sequence[Message], *, response_format: ResponseFormat | None = None,
             disable_thinking: bool = False) -> str:
        text = " ".join(m["content"] for m in messages)
        if "You are the Supervisor" in text:
            return json.dumps({"action": self.supervisor_action, "reasoning": "sim",
                               "target_skill": None, "target_plan_index": None})
        if "You are the Evaluator" in text:
            match = re.search(r"A (strong|weak|moderate) answer", text)
            score = {"strong": 5, "weak": 2, "moderate": 3}[match.group(1) if match else "moderate"]
            return json.dumps({
                "dimensions": {dim: {"score": score, "evidence": "no evidence"} for dim in DIMENSIONS},
                "weighted_score": float(score),
                "confidence": 0.9,
                "follow_up_recommended": False,
                "follow_up_rationale": "sim",
            })
        return json.dumps({"unsupported": True})  # Study Planner etc. degrade gracefully


# --- persona candidate ---------------------------------------------------------------------------


def test_persona_candidate_answers_in_character_for_the_probed_skill():
    persona = Persona(name="p", mastery={"deep_learning": 0.9, "mlops": 0.2})
    client = _PersonaTextClient()
    strong = PersonaCandidate(client, persona, "deep_learning").answer("Explain residual connections.")
    weak = PersonaCandidate(client, persona, "mlops").answer("How do you monitor drift?")
    assert "strong" in strong
    assert "weak" in weak
    # the prompt carried the persona's true level and the asked skill
    assert "deep_learning" in client.calls[0]
    assert "mlops" in client.calls[1]


# --- closed-loop trajectory ----------------------------------------------------------------------


def test_persona_session_converges_on_ground_truth_ordering():
    persona = Persona(name="alice", mastery={
        "deep_learning": 0.9, "ml_fundamentals": 0.5, "mlops": 0.2,
        "system_design": 0.5, "vietnamese_nlp": 0.5,
    })
    final = run_persona_session(
        _SimJudge(), persona, session_id="alice-traj", candidate_client=_PersonaTextClient(),
        max_questions=3, now=lambda: 1.0,
    )

    assert final["status"] == SessionStatus.COMPLETE.value
    probed = probed_ordering(final)
    truth = [s for s in ground_truth_ordering(persona) if s in probed]
    assert probed == truth  # the loop recovered the persona's true ordering among probed Skills
    masteries = posterior_masteries(final)
    assert masteries["deep_learning"] > masteries["mlops"]  # strong Skill ends above the weak one


def test_supervisor_terminates_early_on_a_strong_persona():
    persona = Persona(name="ace", mastery={s: 0.9 for s in [
        "deep_learning", "ml_fundamentals", "mlops", "system_design", "vietnamese_nlp"]})

    final = run_persona_session(
        _SimJudge(supervisor_action="end_early"), persona, session_id="ace-traj",
        candidate_client=_PersonaTextClient(), max_questions=5, now=lambda: 1.0,
    )

    assert final["status"] == SessionStatus.COMPLETE.value
    assert final["stop_reason"] == "supervisor_end_early"
    assert len(final["transcript"]) == 1  # did not burn the 5-question budget on a strong Candidate
    assert max(attempts_by_skill(final).values()) == 1


# --- replay artifact -----------------------------------------------------------------------------


def test_replay_artifact_roundtrips_and_reruns_the_decision_node(tmp_path):
    persona = Persona(name="alice", mastery={"deep_learning": 0.9, "mlops": 0.2})
    final = run_persona_session(
        _SimJudge(), persona, session_id="alice-replay", candidate_client=_PersonaTextClient(),
        max_questions=1, now=lambda: 1.0,
    )

    path = dump_replay_artifact(tmp_path / "trajectory.json", persona, final)
    artifact = load_replay_artifact(path)
    assert artifact.version == REPLAY_ARTIFACT_VERSION
    assert artifact.persona == "alice"
    assert artifact.ground_truth["deep_learning"] == 0.9

    # Counterfactual: re-run the decision node over the dumped state with a *different* model.
    decision = replay_decision(artifact, _SimJudge(supervisor_action="end_early"), now=lambda: 1.0)
    assert decision.action.value == "end_early"
