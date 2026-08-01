"""Typed views over the nested shapes inside ``SessionState`` (R-20 / GH #75).

``SessionState`` is a ``TypedDict`` that LangGraph carries through the graph and SqliteSaver writes
to disk as plain JSON. Its *nested* structures — transcript items, the per-turn dicts inside them,
and Supervisor decision records — were consumed as raw dicts across six modules, so the shape was
re-decided independently at every read site and the writers were the only real specification.

This module types those three shapes and **nothing else**. The top-level ``SessionState`` keys stay
raw `.get` reads on purpose: `language_mode`, `role_criticality`, `session_id` and `started_at` each
have *different* defaults at different call sites (one of them calls `now()`), so a single accessor
per key cannot reproduce current behaviour without a parameter per caller — at which point it is a
worse `.get`.

Two things this module deliberately does not do:

- **It does not validate.** The wire format is the contract; a checkpoint written months ago must
  keep loading. `resolved_weighted_score` is `0.0` on a failed question, which a pydantic model with
  the Evaluator's own `ge=1` bound would reject outright.
- **It does not re-serialize what it read.** A view built by ``from_dict`` refuses ``to_dict``
  (see ``_READ_VIEW_ERROR``): round-tripping would materialise defaults for keys that were absent
  and silently drop keys this module does not know about — the exact way a refactor eats a field.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .microloop import MicroLoopResult, StopReason
from .skill import SkillState, aggregate_evidence_weight

_READ_VIEW_ERROR = (
    "to_dict() is a write-path API: this view was built from an existing dict, and re-serializing it "
    "would materialize defaults for keys that were absent and drop keys this module does not model."
)


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """Read view of one turn's ``trace``. Mirrors ``microloop.TurnTrace`` field for field.

    ``llm_calls``/``llm_calls_by_provider`` default to ``None`` rather than ``0``/``()``: both
    readers use truthiness so the two render identically today, but ``None`` preserves the
    distinction between a pre-R-26 checkpoint that never recorded calls and a turn that genuinely
    made none — which is exactly what the ADR 0009 silent-failover audit reads.
    """

    evaluator_self_critique_triggers: Sequence[str] = ()
    concept_lookup_query: str | None = None
    concept_lookup_skill: str | None = None
    concept_lookup_language: str | None = None
    concept_hit_id: str | None = None
    concept_hit_title: str | None = None
    concept_hit_score: float | None = None
    stop_reason: str | None = None
    llm_calls: int | None = None
    llm_calls_by_provider: Sequence[Sequence[Any]] | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TraceRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """Read view of one micro-loop turn inside a transcript item.

    ``evaluation`` stays an untyped ``Mapping`` and that is load-bearing, not laziness: the exporter
    renders ``dimensions`` in *insertion order* and interpolates the raw score (so ``2`` renders as
    ``2`` and ``2.0`` as ``2.0``), and the Study Planner's retrieval query is built from a stable
    sort over the same dict. Any typed model re-emitting a declared field list would reorder them.
    """

    question: str = ""
    answer: str = ""
    is_follow_up: bool = False
    grounding_concept_id: str | None = None
    grounding_concept_title: str | None = None
    evaluation: Mapping[str, Any] = field(default_factory=dict)
    trace: TraceRecord = field(default_factory=TraceRecord)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TurnRecord:
        return cls(
            question=raw.get("question", ""),
            answer=raw.get("answer", ""),
            is_follow_up=bool(raw.get("is_follow_up", False)),
            grounding_concept_id=raw.get("grounding_concept_id"),
            grounding_concept_title=raw.get("grounding_concept_title"),
            evaluation=raw.get("evaluation") or {},
            trace=TraceRecord.from_dict(raw.get("trace") or {}),
        )


@dataclass(frozen=True, slots=True)
class TranscriptItem:
    """Read/write view of one resolved (or failed) question in the transcript."""

    skill: str
    plan_index: int = 0
    stop_reason: str | None = None
    resolved_weighted_score: float = 0.0
    resolved_confidence: float = 0.0
    evidence_weight: float = 0.0
    skill_state: Mapping[str, Any] | None = None
    turns: tuple[TurnRecord, ...] = ()
    error: str | None = None
    # Set only by ``from_dict``. Marks this instance as a READ view so ``to_dict`` can refuse.
    _raw: Mapping[str, Any] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TranscriptItem:
        """Read view. ``skill`` is subscripted: five existing call sites already require it."""
        return cls(
            skill=str(raw["skill"]),
            plan_index=int(raw.get("plan_index", 0)),
            stop_reason=raw.get("stop_reason"),
            resolved_weighted_score=float(raw.get("resolved_weighted_score", 0)),
            resolved_confidence=float(raw.get("resolved_confidence", 0)),
            evidence_weight=float(raw.get("evidence_weight", 0)),
            skill_state=raw.get("skill_state"),
            turns=tuple(TurnRecord.from_dict(turn) for turn in raw.get("turns") or ()),
            error=raw.get("error"),
            _raw=raw,
        )

    @classmethod
    def from_micro_loop(cls, result: MicroLoopResult, *, plan_index: int) -> dict[str, Any]:
        """The persisted entry for a resolved question. Key order matches the original writer."""
        return {
            "skill": result.skill,
            "plan_index": plan_index,
            "stop_reason": result.stop_reason.value,
            "resolved_weighted_score": result.resolved_evaluation.weighted_score,
            "resolved_confidence": result.resolved_evaluation.confidence,
            # The *total* evidence weight folded into the belief across every turn (issues
            # 0021/0027, R-24), so the scaling is auditable in the export. Since R-24 the belief
            # reads the whole exchange, so the last turn's weight is no longer the weight applied —
            # it differs whenever turns disagree in confidence or one of them escalated to a panel.
            # Same function apply_evaluations sums — one source of truth.
            "evidence_weight": aggregate_evidence_weight([turn.evaluation for turn in result.turns]),
            "skill_state": result.skill_state.to_dict(),
            "turns": [_dump_turn(turn) for turn in result.turns],
        }

    @classmethod
    def failed(cls, skill: str, prior: SkillState, *, plan_index: int, error: BaseException) -> dict[str, Any]:
        """The persisted entry for a question that crashed (slice 0014).

        Carries the same keys as a resolved entry so every consumer keeps working, but with
        zero-evidence sentinels, no turns, the Skill's *unchanged* prior belief (a crash is not
        evidence of low mastery), and a visible ``error`` so the failure is recorded rather than
        swallowed (ADR 0003).
        """
        return {
            "skill": skill,
            "plan_index": plan_index,
            "stop_reason": StopReason.FAILED.value,
            "resolved_weighted_score": 0.0,
            "resolved_confidence": 0.0,
            "evidence_weight": 0.0,  # a crash is not evidence (0014/0021): prior kept, zero weight
            "skill_state": prior.to_dict(),
            "turns": [],
            "error": f"{type(error).__name__}: {error}",
        }

    def to_dict(self) -> dict[str, Any]:
        if self._raw is not None:
            raise TypeError(_READ_VIEW_ERROR)
        out: dict[str, Any] = {
            "skill": self.skill,
            "plan_index": self.plan_index,
            "stop_reason": self.stop_reason,
            "resolved_weighted_score": self.resolved_weighted_score,
            "resolved_confidence": self.resolved_confidence,
            "evidence_weight": self.evidence_weight,
            "skill_state": self.skill_state,
            "turns": [asdict(turn) for turn in self.turns],
        }
        # Absent, never null, on a resolved item — matching the original writer exactly.
        if self.error is not None:
            out["error"] = self.error
        return out


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Read view of one Supervisor decision as persisted in ``supervisor_decisions``.

    ``llm_reasoning`` duplicates ``reasoning`` byte for byte in every record ever written. It is
    kept as its own field rather than de-duplicated because the CLI bare-subscripts it and the
    browser's types declare it; removing it is a wire change, filed separately.
    """

    action: str = ""
    reasoning: str = ""
    target_skill: str | None = None
    target_plan_index: int | None = None
    will_probe_skill: str | None = None
    after_question: int = 0
    from_plan_index: int = 0
    to_plan_index: int = 0
    deviation: bool = False
    llm_reasoning: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DecisionRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})


def _dump_turn(turn: Any) -> dict[str, Any]:
    trace = asdict(turn.trace)
    if turn.trace.stop_reason is not None:
        trace["stop_reason"] = turn.trace.stop_reason.value
    return {
        "question": turn.question,
        "answer": turn.answer,
        "is_follow_up": turn.is_follow_up,
        "grounding_concept_id": turn.grounding_concept_id,
        "grounding_concept_title": turn.grounding_concept_title,
        "evaluation": turn.evaluation.model_dump(mode="json"),
        "trace": trace,
    }


def transcript_items(state: Mapping[str, Any]) -> tuple[TranscriptItem, ...]:
    """Typed view of the Session's transcript."""
    return tuple(TranscriptItem.from_dict(item) for item in state.get("transcript") or ())


def decision_records(state: Mapping[str, Any]) -> tuple[DecisionRecord, ...]:
    """Typed view of the Supervisor's decision trail."""
    return tuple(DecisionRecord.from_dict(record) for record in state.get("supervisor_decisions") or ())


def skill_states_from_mapping(state: Mapping[str, Any]) -> dict[str, SkillState]:
    """Rehydrate every persisted Beta belief, keyed as stored."""
    return {skill: SkillState.from_dict(raw) for skill, raw in state.get("skill_states", {}).items()}


def sorted_skill_states(state: Mapping[str, Any]) -> list[tuple[str, SkillState]]:
    """``(dict key, SkillState)`` pairs sorted by the **dict key**.

    Never ``list[SkillState]`` sorted by ``state.skill``: consumers label rows and look up
    ``skill_metadata`` by the dict key, which is only incidentally equal to ``raw["skill"]``.
    """
    return [(skill, SkillState.from_dict(raw)) for skill, raw in sorted(state.get("skill_states", {}).items())]
