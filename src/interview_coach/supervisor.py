"""Supervisor-owned Macro-loop and LangGraph wiring (slice 0010, ADR 0001/0004).

The Supervisor is intentionally thin: after each resolved Micro-loop it either advances the Topic
Plan or makes one LLM-judged deviation decision. Hard rails such as max questions and max elapsed
seconds run before that model call, so they bound the Session regardless of what the model would
prefer. LangGraph owns only the stateful wiring/checkpoint seam; the existing agents stay unchanged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from .concepts import ConceptStore
from .diagnostic import SKILLS, DiagnosticResult
from .llm import LLMClient, Message, Validator
from .microloop import MicroLoopResult, ScriptedCandidate, run_micro_loop
from .resources import ResourceStore
from .seeds import seed_count, select_seed_question
from .skill import SkillState
from .study_planner import plan_study

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUESTIONS = 5
DEFAULT_MAX_ELAPSED_SECONDS = 30 * 60


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"


class SupervisorAction(StrEnum):
    ADVANCE_PLAN = "advance_plan"
    EXTRA_QUESTION = "extra_question"
    SKIP_AHEAD = "skip_ahead"
    SWITCH_SKILL = "switch_skill"
    END_EARLY = "end_early"


class SessionState(TypedDict, total=False):
    session_id: str
    topic_plan: list[dict[str, Any]]
    skill_states: dict[str, dict[str, float | str]]
    skill_metadata: dict[str, dict[str, Any]]
    current_plan_index: int
    next_skill: str | None
    question_count: int
    max_questions: int
    max_elapsed_seconds: float
    started_at: float
    status: str
    stop_reason: str | None
    transcript: list[dict[str, Any]]
    supervisor_decisions: list[dict[str, Any]]
    study_plan: dict[str, Any] | None
    study_plan_error: str | None


class SupervisorDecision(BaseModel):
    action: SupervisorAction
    reasoning: str = Field(min_length=1)
    target_skill: str | None = None
    target_plan_index: int | None = Field(default=None, ge=0)


SUPERVISOR_SYSTEM_PROMPT = (
    "You are the Supervisor in an adaptive technical interview. You own only the Macro-loop: after a "
    "question is fully resolved, decide whether emerging Skill evidence justifies deviating from the "
    "Topic Plan. You do not judge answers directly, generate Follow-ups, or run Self-critique.\n\n"
    "Allowed actions:\n"
    "- advance_plan: default; move to the next Topic Plan entry.\n"
    "- extra_question: ask one more separate question for the same Skill when evidence is weak or "
    "uncertain.\n"
    "- skip_ahead: skip over already-satisfied plan entries.\n"
    "- switch_skill: probe a different Skill because evidence suggests the current path is less useful.\n"
    "- end_early: finish when the Candidate is consistently strong enough or no useful probe remains.\n\n"
    "Return one JSON object only."
)

_SUPERVISOR_SCHEMA_HINT = (
    '{"action": "advance_plan|extra_question|skip_ahead|switch_skill|end_early", '
    '"reasoning": "<why this macro decision follows from the evidence>", '
    '"target_skill": "<canonical Skill or null>", "target_plan_index": <integer or null>}'
)


def initial_session_state(
    session_id: str,
    diagnostic: DiagnosticResult,
    *,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    max_elapsed_seconds: float = DEFAULT_MAX_ELAPSED_SECONDS,
    started_at: float | None = None,
) -> SessionState:
    """Build the single LangGraph state object from the Diagnostic output."""
    if max_questions < 1:
        raise ValueError("max_questions must be >= 1")
    if max_elapsed_seconds <= 0:
        raise ValueError("max_elapsed_seconds must be > 0")
    topic_plan = [asdict(entry) for entry in diagnostic.topic_plan]
    return {
        "session_id": session_id,
        "topic_plan": topic_plan,
        "skill_states": {
            skill: _dump_skill_state(prior.state)
            for skill, prior in diagnostic.priors.items()
        },
        "skill_metadata": {
            skill: {
                "role_criticality": prior.role_criticality.value,
                "evidence_bar": prior.evidence_bar,
            }
            for skill, prior in diagnostic.priors.items()
        },
        "current_plan_index": 0,
        "next_skill": topic_plan[0]["skill"] if topic_plan else None,
        "question_count": 0,
        "max_questions": max_questions,
        "max_elapsed_seconds": max_elapsed_seconds,
        "started_at": time.time() if started_at is None else started_at,
        "status": SessionStatus.ACTIVE.value,
        "stop_reason": None,
        "transcript": [],
        "supervisor_decisions": [],
        "study_plan": None,
        "study_plan_error": None,
    }


def session_config(session_id: str) -> dict[str, dict[str, str]]:
    """LangGraph checkpoint identity: resume by passing the same Session id as thread_id."""
    return {"configurable": {"thread_id": session_id}}


def build_session_graph(
    client: LLMClient,
    *,
    checkpointer: SqliteSaver | None = None,
    concept_store: ConceptStore | None = None,
    resource_store: ResourceStore | None = None,
    now: Callable[[], float] = time.time,
):
    """Compile the StateGraph that runs one persisted multi-question Session."""

    def question_node(state: SessionState) -> dict[str, Any]:
        if state.get("status") == SessionStatus.COMPLETE.value:
            return {}
        skill = _next_skill(state)
        attempts_for_skill = sum(1 for item in state.get("transcript", []) if item["skill"] == skill)
        seed = select_seed_question(skill, attempts_for_skill)
        before = _load_skill_state(state, skill)
        result = run_micro_loop(
            client,
            seed,
            ScriptedCandidate(seed.answers),
            before,
            max_turns=len(seed.answers),
            concept_store=concept_store,
        )
        skill_states = dict(state["skill_states"])
        skill_states[skill] = _dump_skill_state(result.skill_state)
        transcript = [
            *state.get("transcript", []),
            _dump_micro_loop(result, plan_index=state.get("current_plan_index", 0)),
        ]
        return {
            "skill_states": skill_states,
            "question_count": state.get("question_count", 0) + 1,
            "transcript": transcript,
        }

    def supervisor_node(state: SessionState) -> dict[str, Any]:
        decision = decide_next_move(client, state, now=now)
        return _apply_supervisor_decision(state, decision, now=now)

    def study_plan_node(state: SessionState) -> dict[str, Any]:
        if state.get("status") != SessionStatus.COMPLETE.value or state.get("study_plan"):
            return {}
        # The Study Plan is end-matter produced after a fully-resolved interview. A planner failure
        # (a malformed plan that survives its retry, an empty catalog, a provider blip) must never
        # discard the completed Session — degrade to no plan and let the graph reach END.
        try:
            plan = plan_study(client, state, resource_store=resource_store)
        except Exception as err:  # noqa: BLE001 — last optional node; any failure here must not crash the run
            logger.warning("study planner failed; completing the Session without a Study Plan: %s", err)
            return {"study_plan": None, "study_plan_error": f"{type(err).__name__}: {err}"}
        return {"study_plan": plan.model_dump(mode="json"), "study_plan_error": None}

    graph = StateGraph(SessionState)
    graph.add_node("run_question", question_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("study_plan", study_plan_node)
    graph.add_edge(START, "run_question")
    graph.add_edge("run_question", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: "study_plan" if state.get("status") == SessionStatus.COMPLETE.value else "run_question",
        {"run_question": "run_question", "study_plan": "study_plan"},
    )
    graph.add_edge("study_plan", END)
    return graph.compile(checkpointer=checkpointer)


def decide_next_move(
    client: LLMClient,
    state: SessionState,
    *,
    now: Callable[[], float] = time.time,
) -> SupervisorDecision:
    """Run hard rails first, then ask the Supervisor's single LLM deviation question."""
    if state.get("question_count", 0) >= state.get("max_questions", DEFAULT_MAX_QUESTIONS):
        return SupervisorDecision(
            action=SupervisorAction.END_EARLY,
            reasoning="Hard cap reached: max_questions bound the Session before any LLM deviation choice.",
        )
    elapsed = now() - state.get("started_at", now())
    if elapsed >= state.get("max_elapsed_seconds", DEFAULT_MAX_ELAPSED_SECONDS):
        return SupervisorDecision(
            action=SupervisorAction.END_EARLY,
            reasoning="Hard cap reached: max_elapsed_seconds bound the Session before any LLM deviation choice.",
        )
    # Belt-and-suspenders: advance_plan/skip_ahead already set status COMPLETE when they walk off the
    # end of the plan, so the supervisor node is not re-entered in that case. This guard only matters
    # if a future caller invokes decide_next_move directly on an already-exhausted plan.
    if state.get("current_plan_index", 0) >= len(state.get("topic_plan", [])):
        return SupervisorDecision(
            action=SupervisorAction.END_EARLY,
            reasoning="The Topic Plan is exhausted.",
        )

    return client.chat_json(
        _build_supervisor_messages(state),
        SupervisorDecision,
        validators=_make_supervisor_validators(state),
        max_retries=1,
    )


def export_architecture_diagram(path: str | Path, client: LLMClient) -> Path:
    """Export the LangGraph architecture diagram using draw_mermaid_png()."""
    graph = build_session_graph(client)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(graph.get_graph().draw_mermaid_png())
    return output


def _apply_supervisor_decision(
    state: SessionState,
    decision: SupervisorDecision,
    *,
    now: Callable[[], float],
) -> dict[str, Any]:
    plan = state.get("topic_plan", [])
    current_index = state.get("current_plan_index", 0)
    next_index = current_index
    next_skill: str | None = state.get("next_skill")
    status = SessionStatus.ACTIVE.value
    stop_reason = None

    if decision.action is SupervisorAction.ADVANCE_PLAN:
        next_index = current_index + 1
        next_skill = plan[next_index]["skill"] if next_index < len(plan) else None
        # Walking off the end of the plan completes the Session (the conditional edge then routes to
        # END, so the supervisor node is not re-entered).
        if next_skill is None:
            status = SessionStatus.COMPLETE.value
            stop_reason = "topic_plan_complete"
    elif decision.action is SupervisorAction.EXTRA_QUESTION:
        next_skill = state.get("transcript", [{}])[-1].get("skill", next_skill)
    elif decision.action is SupervisorAction.SKIP_AHEAD:
        next_index = decision.target_plan_index if decision.target_plan_index is not None else current_index + 2
        next_skill = plan[next_index]["skill"] if next_index < len(plan) else None
        if next_skill is None:
            status = SessionStatus.COMPLETE.value
            stop_reason = "topic_plan_complete"
    elif decision.action is SupervisorAction.SWITCH_SKILL:
        next_skill = decision.target_skill
        if next_skill is not None:
            next_index = _plan_index_for_skill(plan, next_skill, default=current_index)
    else:
        status = SessionStatus.COMPLETE.value
        stop_reason = _hard_cap_reason(state, now=now) or "supervisor_end_early"
        next_skill = None

    record = decision.model_dump(mode="json") | {
        "after_question": state.get("question_count", 0),
        "from_plan_index": current_index,
        "to_plan_index": next_index,
        "deviation": decision.action is not SupervisorAction.ADVANCE_PLAN,
        "llm_reasoning": decision.reasoning,
    }
    return {
        "current_plan_index": next_index,
        "next_skill": next_skill,
        "status": status,
        "stop_reason": stop_reason,
        "supervisor_decisions": [*state.get("supervisor_decisions", []), record],
    }


def _build_supervisor_messages(state: SessionState) -> list[Message]:
    evidence = _evidence_summary(state)
    plan_lines = "\n".join(
        f"{i}. {item['skill']} difficulty={item['target_difficulty']} rationale={item['rationale']}"
        for i, item in enumerate(state.get("topic_plan", []))
    )
    user = (
        f"SESSION:\n"
        f"- question_count: {state.get('question_count', 0)} / {state.get('max_questions', DEFAULT_MAX_QUESTIONS)}\n"
        f"- current_plan_index: {state.get('current_plan_index', 0)}\n"
        f"- next_skill: {state.get('next_skill')}\n\n"
        f"TOPIC PLAN:\n{plan_lines or '- empty'}\n\n"
        f"SKILL STATES:\n{_skill_state_summary(state)}\n\n"
        f"RESOLVED QUESTION EVIDENCE:\n{evidence}\n\n"
        f"SEED AVAILABILITY (a Skill with 0 left cannot be probed again):\n{_seed_availability_summary(state)}\n\n"
        "Choose the next Macro-loop move. Prefer advance_plan unless the evidence justifies a "
        "deviation. A consistently strong Candidate may end early; weak or uncertain evidence may "
        "justify extra_question or switch_skill — but only toward a Skill that still has seeds left.\n"
        f"Return JSON shaped like:\n{_SUPERVISOR_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _make_supervisor_validators(state: SessionState) -> list[Validator]:
    skills = set(SKILLS)
    plan_len = len(state.get("topic_plan", []))
    attempts = _attempts_by_skill(state)
    last_skill = state.get("transcript", [{}])[-1].get("skill") if state.get("transcript") else None

    def validate(decision: SupervisorDecision) -> None:
        if decision.target_skill is not None and decision.target_skill not in skills:
            raise ValueError(f"target_skill must be a canonical Skill, got {decision.target_skill!r}")
        if decision.target_plan_index is not None and decision.target_plan_index >= plan_len:
            raise ValueError(f"target_plan_index {decision.target_plan_index} is outside the Topic Plan")
        if decision.action is SupervisorAction.SWITCH_SKILL and decision.target_skill is None:
            raise ValueError("switch_skill requires target_skill")
        if decision.action is SupervisorAction.SKIP_AHEAD and decision.target_plan_index is None:
            raise ValueError("skip_ahead requires target_plan_index")
        # Seed gate: a deviation that probes a Skill with no unused seed would only re-ask an
        # identical question, so it is rejected — the model must advance, switch elsewhere, or end.
        if decision.action is SupervisorAction.EXTRA_QUESTION and not _has_unused_seed(last_skill, attempts):
            raise ValueError(
                f"extra_question is not available for {last_skill!r}: all "
                f"{seed_count(last_skill) if last_skill else 0} seed(s) are used. Choose advance_plan, "
                "switch_skill to a Skill with an unused seed, or end_early."
            )
        if decision.action is SupervisorAction.SWITCH_SKILL and not _has_unused_seed(decision.target_skill, attempts):
            raise ValueError(
                f"switch_skill target {decision.target_skill!r} has no unused seed; pick a Skill that "
                "still has an unused seed or choose advance_plan / end_early."
            )

    return [validate]


def _attempts_by_skill(state: SessionState) -> dict[str, int]:
    """Count how many seed questions have already been asked per Skill (from the transcript)."""
    counts: dict[str, int] = {}
    for item in state.get("transcript", []):
        counts[item["skill"]] = counts.get(item["skill"], 0) + 1
    return counts


def _has_unused_seed(skill: str | None, attempts: Mapping[str, int]) -> bool:
    """True when ``skill`` still has a seed question that has not been asked this Session."""
    if not skill:
        return False
    return attempts.get(skill, 0) < seed_count(skill)


def _next_skill(state: SessionState) -> str:
    if skill := state.get("next_skill"):
        return skill
    plan = state.get("topic_plan", [])
    if not plan:
        raise ValueError("cannot run a Session without a Topic Plan")
    index = min(state.get("current_plan_index", 0), len(plan) - 1)
    return plan[index]["skill"]


def _load_skill_state(state: SessionState, skill: str) -> SkillState:
    raw = state["skill_states"].get(skill)
    if raw is None:
        return SkillState.neutral(skill)
    return SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))


def _dump_skill_state(state: SkillState) -> dict[str, float | str]:
    return {"skill": state.skill, "alpha": state.alpha, "beta": state.beta}


def _dump_micro_loop(result: MicroLoopResult, *, plan_index: int) -> dict[str, Any]:
    def dump_trace(turn) -> dict[str, Any]:
        trace = asdict(turn.trace)
        if turn.trace.stop_reason is not None:
            trace["stop_reason"] = turn.trace.stop_reason.value
        return trace

    return {
        "skill": result.skill,
        "plan_index": plan_index,
        "stop_reason": result.stop_reason.value,
        "resolved_weighted_score": result.resolved_evaluation.weighted_score,
        "resolved_confidence": result.resolved_evaluation.confidence,
        "skill_state": _dump_skill_state(result.skill_state),
        "turns": [
            {
                "question": turn.question,
                "answer": turn.answer,
                "is_follow_up": turn.is_follow_up,
                "grounding_concept_id": turn.grounding_concept_id,
                "grounding_concept_title": turn.grounding_concept_title,
                "evaluation": turn.evaluation.model_dump(mode="json"),
                "trace": dump_trace(turn),
            }
            for turn in result.turns
        ],
    }


def _skill_state_summary(state: SessionState) -> str:
    lines = []
    for skill, raw in sorted(state.get("skill_states", {}).items()):
        s = SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))
        meta = state.get("skill_metadata", {}).get(skill, {})
        lines.append(
            f"- {skill}: mastery={s.mastery:.3f}, confidence={s.confidence:.3f}, "
            f"criticality={meta.get('role_criticality', 'unknown')}, evidence_bar={meta.get('evidence_bar', 'n/a')}"
        )
    return "\n".join(lines) or "- none"


def _evidence_summary(state: SessionState) -> str:
    rows = []
    for i, item in enumerate(state.get("transcript", []), start=1):
        rows.append(
            f"- Q{i} skill={item['skill']} score={item['resolved_weighted_score']:.2f} "
            f"confidence={item['resolved_confidence']:.2f} stop={item['stop_reason']}"
        )
    return "\n".join(rows) or "- none"


def _seed_availability_summary(state: SessionState) -> str:
    attempts = _attempts_by_skill(state)
    lines = []
    for skill in SKILLS:
        used = attempts.get(skill, 0)
        total = seed_count(skill)
        lines.append(f"- {skill}: probed {used}/{total} seeds ({max(0, total - used)} left)")
    return "\n".join(lines)


def _plan_index_for_skill(plan: list[dict[str, Any]], skill: str, *, default: int) -> int:
    for i, item in enumerate(plan):
        if item["skill"] == skill:
            return i
    return default


def _hard_cap_reason(
    state: SessionState,
    *,
    now: Callable[[], float],
) -> Literal["max_questions", "max_elapsed_seconds"] | None:
    if state.get("question_count", 0) >= state.get("max_questions", DEFAULT_MAX_QUESTIONS):
        return "max_questions"
    elapsed = now() - state.get("started_at", now())
    if elapsed >= state.get("max_elapsed_seconds", DEFAULT_MAX_ELAPSED_SECONDS):
        return "max_elapsed_seconds"
    return None
