"""The within-question Micro-loop (slice 0005, ADR 0001), hand-rolled in plain Python.

The cycle that owns a single question end-to-end: the Interviewer asks → the Candidate answers → the
Evaluator scores the turn and flags ``follow_up_recommended`` → if a Follow-up is flagged *and* the
safety cap is not hit, the Interviewer generates one targeting the gap and we repeat → otherwise stop
and keep the last score. The Evaluator's flag is the stop logic; the cap is only a guardrail against a
pathological loop, and tripping it is logged distinctly from a normal resolution. On exit the resolved
score updates the Skill state (slice 0002).

Orchestration is deliberately plain Python — LangGraph is deferred to slice 0010 (ADR 0004). The only
tool-using agent is still the Interviewer; the micro-loop just passes the active Skill into
``generate_follow_up`` so that concept lookup can be metadata-filtered (ADR 0003).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from .concepts import ConceptStore
from .evaluator import Evaluation, PanelBudget, evaluate
from .interviewer import FollowUpUnavailable, generate_follow_up, render_seed_question
from .language import DEFAULT_LANGUAGE_MODE, rubric_with_delivery
from .llm import LLMClient
from .seeds import SeedQuestion
from .skill import SkillState, apply_evaluation

logger = logging.getLogger(__name__)

# 1 original question + up to 3 follow-ups. A guardrail, not the stop logic: a healthy loop stops
# earlier because the Evaluator stops recommending follow-ups.
DEFAULT_MAX_TURNS = 4


class CandidateIntent(RuntimeError):
    """Base class for Candidate-driven control signals (ADR 0005).

    These represent the Candidate asking to *stop* — EOF/Ctrl-D on stdin, a web cancel or disconnect,
    or a scripted Candidate with nothing left to say. Per ADR 0005 they must propagate *out of* every
    failure-isolation net (issue 0014's per-question ``except``) and abort or suspend the Session:
    human intent must never be converted into fake skill evidence. Infrastructure failures
    (provider/tool/schema errors) are the opposite kind and stay eligible for the
    record-`failed`-and-advance net. The classification lives on the exception taxonomy so every
    transport — terminal, WebSocket, and future elicitation flows — is handled the same way.
    """


class CandidateExhausted(CandidateIntent):
    """A scripted Candidate was asked more questions than it has canned answers for."""


class CandidateInputUnavailable(CandidateIntent):
    """An interactive Candidate could not read terminal input (EOF/Ctrl-D), or a web cancel/disconnect."""


class Candidate(Protocol):
    """Whoever answers the Interviewer within a question. A fixture here; a human/UI later (0012)."""

    def answer(self, question: str) -> str: ...


class ScriptedCandidate:
    """A fixture Candidate that replies with canned answers in order (issue 0005: the Candidate is a
    fixture). The first reply answers the seed question; the rest answer successive Follow-ups."""

    def __init__(self, answers: Sequence[str]) -> None:
        if not answers:
            raise ValueError("a scripted candidate needs at least one answer")
        self._answers = list(answers)
        self._index = 0

    def answer(self, question: str) -> str:
        if self._index >= len(self._answers):
            raise CandidateExhausted(
                f"scripted candidate ran out of answers after {self._index} turn(s); "
                "the micro-loop asked more follow-ups than were scripted"
            )
        reply = self._answers[self._index]
        self._index += 1
        return reply


class InteractiveCandidate:
    """Terminal-backed Candidate for MVP prep Sessions.

    The Candidate can type multiple lines and finish with a blank line. A blank first line is allowed
    and is treated as an empty answer, which lets the Evaluator handle it normally.
    """

    def __init__(self, input_func: Callable[[str], str] = input, print_func: Callable[[str], None] = print) -> None:
        self._input = input_func
        self._print = print_func

    def answer(self, question: str) -> str:
        self._print(f"\nInterviewer:\n{question}\n")
        self._print("Candidate answer (finish with a blank line):")
        lines: list[str] = []
        while True:
            try:
                line = self._input("> " if not lines else "... ")
            except EOFError as err:
                raise CandidateInputUnavailable(
                    "interactive Candidate input ended before an answer was provided; "
                    "run in a terminal or pass --scripted for non-interactive demos"
                ) from err
            if not line.strip():
                return "\n".join(lines)
            lines.append(line)


def _escalation_triggers(evaluation: Evaluation) -> tuple[str, ...]:
    """The deterministic triggers that escalated this judgment, wherever the trace lives.

    New escalations carry a PanelTrace (issue 0027); pre-panel checkpoints carry SelfCritiqueTrace.
    """
    if evaluation.panel is not None:
        return evaluation.panel.triggers
    if evaluation.self_critique is not None:
        return evaluation.self_critique.triggers
    return ()


class StopReason(StrEnum):
    """Why the micro-loop stopped — a normal resolution vs. a guardrail trip (see acceptance crit.)."""

    RESOLVED = "resolved"  # the Evaluator stopped recommending a follow-up — the real stop logic
    SAFETY_CAP = "safety_cap"  # the cap halted a still-flagging loop — a guardrail, not a stop
    # A follow-up was wanted but could not be generated (a persistent malformed tool call); the loop
    # resolves with the last score instead of crashing the question. A degrade, not a normal stop.
    FOLLOW_UP_UNAVAILABLE = "follow_up_unavailable"
    # The question itself blew up (an Evaluator/Interviewer error survived its retries); the Session
    # records the question as failed and moves on instead of aborting (slice 0014). Set by the
    # Supervisor's question_node, never by the micro-loop, which by then has already crashed.
    FAILED = "failed"


@dataclass(frozen=True)
class TurnTrace:
    """Debug trace for the agent decisions attached to one micro-loop turn.

    Concept lookup fields describe the Follow-up generated because of this turn's evaluation. The
    Follow-up turn itself still carries ``grounding_concept_id`` for transcript display.
    """

    evaluator_self_critique_triggers: tuple[str, ...] = ()
    concept_lookup_query: str | None = None
    concept_lookup_skill: str | None = None
    concept_lookup_language: str | None = None
    concept_hit_id: str | None = None
    concept_hit_title: str | None = None
    concept_hit_score: float | None = None
    stop_reason: StopReason | None = None


@dataclass(frozen=True)
class Turn:
    """One ask→answer→score step of the micro-loop."""

    question: str
    answer: str
    evaluation: Evaluation
    is_follow_up: bool  # False for the seed question, True for an Interviewer-generated follow-up
    grounding_concept_id: str | None = None
    grounding_concept_title: str | None = None
    trace: TurnTrace = TurnTrace()


@dataclass(frozen=True)
class MicroLoopResult:
    """The outcome of resolving one question: the full exchange, why it stopped, and the new belief."""

    skill: str
    turns: tuple[Turn, ...]
    stop_reason: StopReason
    skill_state: SkillState  # the Skill state after folding in the resolved score (slice 0002)

    @property
    def resolved_evaluation(self) -> Evaluation:
        """The kept score: the last turn's evaluation (slice 0005 keeps the last, not the best)."""
        return self.turns[-1].evaluation


def run_micro_loop(
    client: LLMClient,
    seed: SeedQuestion,
    candidate: Candidate,
    state: SkillState | None = None,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    concept_store: ConceptStore | None = None,
    language_mode: str = DEFAULT_LANGUAGE_MODE,
    interviewer_client: LLMClient | None = None,
) -> MicroLoopResult:
    """Resolve one question end-to-end, returning the exchange and the updated Skill state.

    ``state`` is the Skill's belief coming in (a Session threads it across questions in the macro-loop,
    slice 0010); it defaults to the neutral prior. The Evaluator scores *every* turn and the last score
    is what the question resolves to — even when the safety cap fires. ``language_mode`` (issue 0024)
    renders the seed question in the Session's language, makes follow-ups speak it, and activates
    ``english_delivery`` per answer — deterministically, so a vn Session can never score delivery.
    """
    if max_turns < 1:
        raise ValueError(f"max_turns must be >= 1, got {max_turns}")
    if state is None:
        state = SkillState.neutral(seed.skill)

    # ADR 0010: the Evaluator (``client``) and the Interviewer may run on different role clients.
    # A single client stays valid — every existing caller and test passes one and gets both roles.
    interviewer = interviewer_client if interviewer_client is not None else client

    turns: list[Turn] = []
    question = render_seed_question(interviewer, seed.question, language_mode)
    is_follow_up = False
    grounding_concept_id: str | None = None
    grounding_concept_title: str | None = None
    # One committee per question, not per turn: every turn of a collapsing exchange re-triggering
    # the panel would pay 3 extra calls each time — the budget is the free-tier cost rail.
    panel_budget = PanelBudget.per_question()

    while True:
        answer = candidate.answer(question)
        rubric = rubric_with_delivery(seed.rubric, language_mode, answer)
        evaluation = evaluate(client, question, answer, rubric, language_mode=language_mode, panel_budget=panel_budget)
        turn = Turn(
            question=question,
            answer=answer,
            evaluation=evaluation,
            is_follow_up=is_follow_up,
            grounding_concept_id=grounding_concept_id,
            grounding_concept_title=grounding_concept_title,
            trace=TurnTrace(evaluator_self_critique_triggers=_escalation_triggers(evaluation)),
        )

        if not evaluation.follow_up_recommended:
            stop_reason = StopReason.RESOLVED
            turns.append(replace(turn, trace=replace(turn.trace, stop_reason=stop_reason)))
            logger.info(
                "micro-loop resolved after %d turn(s): the Evaluator no longer recommends a follow-up",
                len(turns),
            )
            break

        if len(turns) + 1 >= max_turns:
            stop_reason = StopReason.SAFETY_CAP
            turns.append(replace(turn, trace=replace(turn.trace, stop_reason=stop_reason)))
            logger.warning(
                "micro-loop SAFETY CAP tripped after %d turn(s): the Evaluator still recommends a "
                "follow-up but the cap (max_turns=%d) halts the loop — this is a guardrail trip, NOT a "
                "normal resolution; keeping the last score",
                len(turns),
                max_turns,
            )
            break

        try:
            follow_up = generate_follow_up(
                interviewer,
                original_question=seed.question,
                answer=answer,
                evaluation=evaluation,
                skill=seed.skill,
                concept_store=concept_store,
                language_mode=language_mode,
            )
        except FollowUpUnavailable as err:
            # The Evaluator wanted a follow-up but the Interviewer could not produce one (a persistent
            # malformed tool call survived its retry). Resolve with the last score rather than letting
            # one transient LLM glitch crash the question and the whole Session.
            stop_reason = StopReason.FOLLOW_UP_UNAVAILABLE
            turns.append(replace(turn, trace=replace(turn.trace, stop_reason=stop_reason)))
            logger.warning(
                "micro-loop could not obtain a follow-up after %d turn(s) (%s); keeping the last score "
                "and resolving instead of crashing the question",
                len(turns),
                err,
            )
            break

        turns.append(
            replace(
                turn,
                trace=replace(
                    turn.trace,
                    concept_lookup_query=follow_up.concept_lookup_query,
                    concept_lookup_skill=follow_up.concept_lookup_skill,
                    concept_lookup_language=follow_up.concept_lookup_language,
                    concept_hit_id=follow_up.concept_id,
                    concept_hit_title=follow_up.concept_title,
                    concept_hit_score=follow_up.concept_score,
                ),
            )
        )
        question = follow_up.question
        is_follow_up = True
        grounding_concept_id = follow_up.concept_id
        grounding_concept_title = follow_up.concept_title

    resolved = turns[-1].evaluation
    return MicroLoopResult(
        skill=seed.skill,
        turns=tuple(turns),
        stop_reason=stop_reason,
        skill_state=apply_evaluation(state, resolved),
    )
