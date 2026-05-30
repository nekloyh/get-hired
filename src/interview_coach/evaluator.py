"""The Evaluator: the single judge of answer quality (ADR 0001).

It scores one answer against the active rubric dimensions, quoting verbatim evidence, and decides
whether a follow-up is warranted — framed around *marginal information gain*, not a score threshold.
Slice 0001 is a single structured LLM call: answer in, typed judgment out. No skill-state, no loop.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .llm import LLMClient, Message, Validator
from .rubric import Rubric

NO_EVIDENCE = "no evidence"


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
                    f"Copy an exact phrase from the answer, or use '{NO_EVIDENCE}'."
                )

    return [check_dimensions, check_evidence]


SYSTEM_PROMPT = (
    "You are the Evaluator in a mock technical interview. You are the single judge of answer "
    "quality: you score the candidate's answer against a rubric and decide whether a follow-up is "
    "warranted. You never ask questions and you never coach — you only judge.\n\n"
    "Rules:\n"
    "- Score ONLY the rubric dimensions listed below, each an integer 1–5.\n"
    "- For every dimension, 'evidence' MUST be an exact, verbatim quote copied from the candidate's "
    f"answer, or the literal string '{NO_EVIDENCE}' if the answer offers none.\n"
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


def evaluate(client: LLMClient, question: str, answer: str, rubric: Rubric) -> Evaluation:
    """Run the Evaluator on one question + answer and return a typed, validated judgment."""
    return client.chat_json(
        _build_messages(question, answer, rubric),
        Evaluation,
        validators=_make_validators(rubric, answer),
        max_retries=1,
    )
