"""The Evaluator: the single judge of answer quality (ADR 0001).

It scores one answer against the active rubric dimensions, quoting verbatim evidence, and decides
whether a follow-up is warranted — framed around *marginal information gain*, not a score threshold.
Slice 0001 is a single structured LLM call: answer in, typed judgment out. No skill-state, no loop.

Slice 0003 adds a deterministic guard *after* that call: we recompute the linear weighted score in
Python and, when the model's holistic ``weighted_score`` diverges from it beyond a tolerance, lower
``confidence`` so self-critique (slice 0006) re-checks the judgment. The score itself is left
untouched — the model is allowed its non-linear judgment (e.g. capping a fatally wrong answer); the
divergence is only an alarm, and the model agreeing with its own arithmetic is a free confidence
signal.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from .llm import LLMClient, Message, Validator
from .rubric import Rubric

logger = logging.getLogger(__name__)

NO_EVIDENCE = "no evidence"

_EVIDENCE_RULE = (
    f"'evidence' MUST be ONE contiguous substring copied character-for-character from the "
    f"candidate's answer — do not join multiple spans and do not paraphrase. "
    f"Use the literal string '{NO_EVIDENCE}' when the answer offers none."
)


class DimensionScore(BaseModel):
    score: int = Field(ge=1, le=5, description="1 (poor) to 5 (excellent).")
    evidence: str = Field(
        description="A verbatim quote from the candidate's answer, or the literal text 'no evidence'."
    )


class Evaluation(BaseModel):
    """The Evaluator's typed judgment of a single answer."""

    dimensions: dict[str, DimensionScore]
    weighted_score: float = Field(
        ge=1, le=5, description="The Evaluator's holistic, weight-aware aggregate (1–5)."
    )
    confidence: float = Field(ge=0, le=1)
    follow_up_recommended: bool
    follow_up_rationale: str = Field(
        description="Whether one more probing question would reveal something not already known."
    )


def _make_validators(rubric: Rubric, answer: str) -> list[Validator]:
    """Domain validators that the LLM call must satisfy (the retry self-corrects on failure)."""
    expected = set(rubric.active)

    def check_dimensions(ev: Evaluation) -> None:
        got = set(ev.dimensions)
        if missing := expected - got:
            raise ValueError(f"missing scores for active dimensions: {sorted(missing)}")
        if extra := got - expected:
            raise ValueError(f"do not score these dimensions (weight 0): {sorted(extra)}")

    def check_evidence(ev: Evaluation) -> None:
        for dim, ds in ev.dimensions.items():
            quote = ds.evidence.strip()
            if quote.lower() == NO_EVIDENCE:
                continue
            if not quote or quote not in answer:
                raise ValueError(
                    f"evidence for '{dim}' is not a verbatim quote from the answer: {quote!r}. "
                    f"{_EVIDENCE_RULE}"
                )

    return [check_dimensions, check_evidence]


SYSTEM_PROMPT = (
    "You are the Evaluator in a mock technical interview. You are the single judge of answer "
    "quality: you score the candidate's answer against a rubric and decide whether a follow-up is "
    "warranted. You never ask questions and you never coach — you only judge.\n\n"
    "Rules:\n"
    "- Score ONLY the rubric dimensions listed below, each an integer 1–5.\n"
    f"- For every dimension, {_EVIDENCE_RULE}\n"
    "- 'weighted_score' (1–5) is your holistic, weight-aware aggregate of the dimensions.\n"
    "- 'confidence' (0–1) is how sure you are of this judgment.\n"
    "- 'follow_up_recommended' is about MARGINAL INFORMATION GAIN — would one more probing question "
    "likely reveal something you do not already know about this candidate's skill? It is NOT a score "
    "threshold: a strong answer can still warrant a follow-up, and a weak but fully-revealed answer "
    "may not.\n"
    "- Respond with a single JSON object only — no prose, no code fences."
)

_SCHEMA_HINT = (
    '{"dimensions": {"<dimension>": {"score": <1-5>, "evidence": "<verbatim quote|no evidence>"}}, '
    '"weighted_score": <1-5>, "confidence": <0-1>, '
    '"follow_up_recommended": <true|false>, "follow_up_rationale": "<text>"}'
)


def _build_messages(question: str, answer: str, rubric: Rubric) -> list[Message]:
    user = (
        f"QUESTION:\n{question}\n\n"
        f"CANDIDATE ANSWER:\n{answer}\n\n"
        f"RUBRIC — score exactly these dimensions:\n{rubric.render()}\n\n"
        f"Return JSON shaped like:\n{_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# --- Deterministic weighted_score cross-check (slice 0003) -------------------------------------

# A full point of disagreement on the 1–5 scale is the alarm. Some gap is legitimate — the holistic
# score may intentionally diverge from the mechanical mean (capping a fatally wrong answer) — so the
# tolerance is wide enough not to fire on rounding or mild non-linearity, and the check is symmetric
# (an *inflated* bottom-line over weak dimensions is the case we most want to catch, but a sharp cap
# is also worth a second look).
WEIGHTED_SCORE_TOLERANCE = 1.0

# When the cross-check trips, confidence is capped here — clearly "low" so self-critique (slice 0006,
# which owns the actual trigger threshold and should set it at or above this) re-checks the judgment.
# Using min() means we only ever lower confidence, never raise it, and re-applying the guard is a
# no-op. A score the model was already unsure about (confidence already <= this) is left untouched —
# it is already in low-confidence territory.
DIVERGENCE_CONFIDENCE_CEILING = 0.4


def linear_weighted_score(dimensions: dict[str, DimensionScore], rubric: Rubric) -> float:
    """The mechanical weighted mean of the dimension scores (1–5), normalized by the active weights.

    This is the deterministic counterpart to the Evaluator's holistic ``weighted_score``; the gap
    between the two is the cross-check signal. Expects ``dimensions`` to be a validated evaluation's
    scores (keys are exactly the rubric's active dimensions, so every weight here is > 0).
    """
    total_weight = sum(rubric.weights[d] for d in dimensions)
    if total_weight <= 0:
        raise ValueError("cannot cross-check: active rubric weights sum to 0")
    return sum(rubric.weights[d] * ds.score for d, ds in dimensions.items()) / total_weight


def apply_cross_check(evaluation: Evaluation, rubric: Rubric) -> Evaluation:
    """Lower ``confidence`` when the holistic ``weighted_score`` diverges from the linear one.

    Keeps the holistic ``weighted_score`` untouched (the non-linear judgment is the point) and only
    caps ``confidence`` so self-critique re-checks divergent judgments. Returns the evaluation
    unchanged when the two scores agree within :data:`WEIGHTED_SCORE_TOLERANCE`.
    """
    linear = linear_weighted_score(evaluation.dimensions, rubric)
    divergence = abs(evaluation.weighted_score - linear)
    if divergence <= WEIGHTED_SCORE_TOLERANCE:
        return evaluation
    guarded = min(evaluation.confidence, DIVERGENCE_CONFIDENCE_CEILING)
    if guarded == evaluation.confidence:
        return evaluation
    logger.info(
        "weighted_score cross-check tripped: holistic=%.2f vs linear=%.2f (Δ=%.2f > tol %.2f); "
        "lowering confidence %.2f -> %.2f",
        evaluation.weighted_score,
        linear,
        divergence,
        WEIGHTED_SCORE_TOLERANCE,
        evaluation.confidence,
        guarded,
    )
    return evaluation.model_copy(update={"confidence": guarded})


def evaluate(client: LLMClient, question: str, answer: str, rubric: Rubric) -> Evaluation:
    """Run the Evaluator on one question + answer and return a typed, validated judgment.

    The structured LLM call is followed by the deterministic cross-check (slice 0003), which may
    lower ``confidence`` when the holistic and linear weighted scores disagree.
    """
    evaluation = client.chat_json(
        _build_messages(question, answer, rubric),
        Evaluation,
        validators=_make_validators(rubric, answer),
        max_retries=1,
    )
    return apply_cross_check(evaluation, rubric)
