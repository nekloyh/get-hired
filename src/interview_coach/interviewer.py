"""The Interviewer: drives the conversation within a single question (ADR 0001).

It asks the question and, when the Evaluator's ``follow_up_recommended`` flag asks for one, it
*generates* a Follow-up that targets the gap the Evaluator found. It never judges or scores — that is
the Evaluator's job alone (ADR 0001 / CONTEXT.md). The Interviewer owns *depth* mechanically (it runs
the micro-loop) but not the judgment that drives it.

For this slice the Follow-up is a single-shot ``chat_json`` call with the exchange injected directly.
The RAG ``lookup_concept`` tool that makes the Interviewer the one tool-using agent (ADR 0003) arrives
in slice 0007; until then there are no tools, so the MiMo ``reasoning_content`` trap never fires here.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from .evaluator import Evaluation
from .llm import LLMClient, Message, Validator

logger = logging.getLogger(__name__)


class FollowUp(BaseModel):
    """A probing question asked within the same original question to stress-test a weak answer."""

    question: str = Field(min_length=1, description="The follow-up question to put to the candidate.")
    targets: str = Field(
        min_length=1,
        description="The specific gap or weak dimension this follow-up probes — for traceability.",
    )


SYSTEM_PROMPT = (
    "You are the Interviewer in a mock technical interview. You drive the conversation within a "
    "single question. You never judge, score, or coach — a separate Evaluator does all judging. Your "
    "one job right now: the candidate's answer was weak in a specific way, and you must ask ONE "
    "follow-up question that targets that exact gap.\n\n"
    "Rules:\n"
    "- The follow-up MUST probe the weakness the Evaluator flagged — push for the missing mechanism, "
    "trade-off, or concrete detail.\n"
    "- It MUST NOT be answerable by simply repeating the original answer. If the candidate could "
    "satisfy it by restating what they already said, it is a bad follow-up.\n"
    "- Ask exactly one focused question. Do not stack multiple questions or add commentary.\n"
    "- Respond with a single JSON object only — no prose, no code fences."
)

_SCHEMA_HINT = '{"question": "<one focused follow-up>", "targets": "<the gap it probes>"}'


def _format_assessment(evaluation: Evaluation) -> str:
    """Render the Evaluator's per-dimension scores (weakest first) plus its follow-up rationale.

    Feeding the weak dimensions and their verbatim evidence is what lets the Interviewer aim the
    follow-up at the gap rather than re-asking the question.
    """
    lines = [
        f"- {dim}: {ds.score}/5 (evidence: {ds.evidence!r})"
        for dim, ds in sorted(evaluation.dimensions.items(), key=lambda kv: kv[1].score)
    ]
    lines.append(f"- evaluator's follow-up rationale: {evaluation.follow_up_rationale}")
    return "\n".join(lines)


def _build_messages(original_question: str, answer: str, evaluation: Evaluation) -> list[Message]:
    user = (
        f"ORIGINAL QUESTION:\n{original_question}\n\n"
        f"CANDIDATE'S LATEST ANSWER:\n{answer}\n\n"
        f"EVALUATOR'S ASSESSMENT (weakest dimensions first):\n{_format_assessment(evaluation)}\n\n"
        "Generate one follow-up that targets the weakest area above and cannot be answered by "
        f"repeating the answer.\nReturn JSON shaped like:\n{_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _normalize(question: str) -> str:
    """Fold case, whitespace, and edge punctuation so a re-ask is recognised despite cosmetic edits."""
    return " ".join(question.lower().split()).strip(" \t\n?.!,:;")


def _make_validators(original_question: str) -> list[Validator]:
    """Quality gates a generated Follow-up must clear (the chat_json retry self-corrects on failure).

    Slice 0007 (the RAG, tool-using Interviewer) extends this list with grounding checks without
    touching the micro-loop's control flow — the loop only ever calls :func:`generate_follow_up`.
    """
    target = _normalize(original_question)

    def reject_reask(fu: FollowUp) -> None:
        # A Follow-up that just restates the question is answerable by repeating the original answer,
        # which the acceptance criterion forbids.
        if _normalize(fu.question) == target:
            raise ValueError(
                "the follow-up just re-asks the original question — it must probe the specific gap "
                "and must not be answerable by repeating the original answer"
            )

    return [reject_reask]


def generate_follow_up(
    client: LLMClient,
    *,
    original_question: str,
    answer: str,
    evaluation: Evaluation,
) -> FollowUp:
    """Generate one Follow-up that targets the gap the Evaluator flagged (single-shot, no tools)."""
    follow_up = client.chat_json(
        _build_messages(original_question, answer, evaluation),
        FollowUp,
        validators=_make_validators(original_question),
        max_retries=1,
    )
    logger.info("interviewer follow-up targets %r: %s", follow_up.targets, follow_up.question)
    return follow_up
