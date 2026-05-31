"""The Interviewer: drives the conversation within a single question (ADR 0001).

It asks the question and, when the Evaluator's ``follow_up_recommended`` flag asks for one, it
*generates* a Follow-up that targets the gap the Evaluator found. It never judges or scores — that is
the Evaluator's job alone (ADR 0001 / CONTEXT.md). The Interviewer owns *depth* mechanically (it runs
the micro-loop) but not the judgment that drives it.

Slice 0007 gives this agent the project's only tool: ``lookup_concept``. The Interviewer performs a
small ReAct loop: the model emits provider-level ``tool_calls``, Python executes the lookup, and the
result is fed back as a ``tool`` turn before the model writes the grounded Follow-up. MiMo thinking
mode is disabled so ``reasoning_content`` never has to be replayed through a multi-turn tool history
(ADR 0003). A JSON tool-plan fallback exists only for non-native test/dummy clients.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from pydantic import BaseModel, Field, field_validator

from .concepts import ConceptLookup, ConceptStore, lookup_concept, seed_concept_store
from .evaluator import Evaluation
from .llm import LLMClient, Message, ToolCallingUnsupported, ToolSpec, Validator

logger = logging.getLogger(__name__)


class FollowUp(BaseModel):
    """A probing question asked within the same original question to stress-test a weak answer."""

    question: str = Field(min_length=1, description="The follow-up question to put to the candidate.")
    targets: str = Field(
        min_length=1,
        description="The specific gap or weak dimension this follow-up probes — for traceability.",
    )
    concept_id: str | None = Field(default=None, description="The retrieved concept note that grounded it.")
    concept_title: str | None = Field(default=None, description="Human-readable title of the grounding note.")


class ConceptToolRequest(BaseModel):
    """The Interviewer's planned call to its one tool."""

    query: str = Field(min_length=1, description="Semantic query for lookup_concept.")
    skill: str | None = Field(default=None, description="Optional Skill metadata filter.")
    language: str | None = Field(default=None, description="Optional language metadata filter.")
    reason: str = Field(min_length=1, description="Why this concept lookup should help the Follow-up.")

    @field_validator("skill", "language", mode="before")
    @classmethod
    def _normalize_optional(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in {"", "null", "none", "n/a"}:
                return None
            return normalized
        return value


TOOL_SYSTEM_PROMPT = (
    "You are the Interviewer in a mock technical interview. You never judge, score, or coach — a "
    "separate Evaluator does all judging. You have exactly one tool available: lookup_concept(query, "
    "skill, language). Before asking a Follow-up, choose the single concept lookup that will best "
    "ground a question targeting the Evaluator's flagged gap.\n\n"
    "Rules:\n"
    "- Produce exactly one lookup_concept request.\n"
    "- Use the Skill metadata filter when it is provided; this is mandatory for Vietnamese NLP notes.\n"
    "- Use language='vi' only when the target Skill or missing concept is Vietnamese-specific.\n"
    "- Respond with a single JSON object only — no prose, no code fences."
)

FOLLOW_UP_SYSTEM_PROMPT = (
    "You are the Interviewer in a mock technical interview. You drive the conversation within a "
    "single question. You never judge, score, or coach — a separate Evaluator does all judging. Your "
    "one job right now: use the retrieved concept note to ask ONE follow-up question that targets "
    "the exact gap the Evaluator flagged.\n\n"
    "Rules:\n"
    "- The follow-up MUST probe the weakness the Evaluator flagged — push for the missing mechanism, "
    "trade-off, or concrete detail.\n"
    "- The retrieved concept note MUST materially shape the question; use its mechanism or failure "
    "mode rather than asking a generic prompt.\n"
    "- It MUST NOT be answerable by simply repeating the original answer. If the candidate could "
    "satisfy it by restating what they already said, it is a bad follow-up.\n"
    "- Ask exactly one focused question. Do not stack multiple questions or add commentary.\n"
    "- Respond with a single JSON object only — no prose, no code fences."
)

_TOOL_SCHEMA_HINT = (
    '{"query": "<lookup_concept query>", "skill": "<skill|null>", '
    '"language": "<language|null>", "reason": "<why this lookup helps>"}'
)
_FOLLOW_UP_SCHEMA_HINT = '{"question": "<one focused follow-up>", "targets": "<the gap it probes>"}'


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


def _build_tool_messages(
    original_question: str,
    answer: str,
    evaluation: Evaluation,
    skill: str | None,
) -> list[Message]:
    user = (
        f"ORIGINAL QUESTION:\n{original_question}\n\n"
        f"TARGET SKILL:\n{skill or 'unknown'}\n\n"
        f"CANDIDATE'S LATEST ANSWER:\n{answer}\n\n"
        f"EVALUATOR'S ASSESSMENT (weakest dimensions first):\n{_format_assessment(evaluation)}\n\n"
        "Choose the one lookup_concept call that will provide the most useful background for a "
        f"targeted Follow-up.\nReturn JSON shaped like:\n{_TOOL_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": TOOL_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _build_follow_up_messages(
    original_question: str,
    answer: str,
    evaluation: Evaluation,
    lookup: ConceptLookup,
) -> list[Message]:
    user = (
        f"ORIGINAL QUESTION:\n{original_question}\n\n"
        f"CANDIDATE'S LATEST ANSWER:\n{answer}\n\n"
        f"EVALUATOR'S ASSESSMENT (weakest dimensions first):\n{_format_assessment(evaluation)}\n\n"
        f"RETRIEVED CONCEPT NOTE FROM lookup_concept:\n{lookup.render()}\n\n"
        "Generate one follow-up that targets the weakest area above and cannot be answered by "
        f"repeating the answer.\nReturn JSON shaped like:\n{_FOLLOW_UP_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": FOLLOW_UP_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _normalize(question: str) -> str:
    """Fold case, whitespace, and edge punctuation so a re-ask is recognised despite cosmetic edits."""
    return " ".join(question.lower().split()).strip(" \t\n?.!,:;")


def _grounding_terms(lookup: ConceptLookup) -> set[str]:
    text = f"{lookup.note.title} {' '.join(lookup.note.tags)} {lookup.note.content}"
    return {term for term in _normalize(text).split() if len(term) >= 4}


def _make_validators(
    original_question: str,
    get_lookup: Callable[[], ConceptLookup | None],
) -> list[Validator]:
    """Quality gates a generated Follow-up must clear (the chat_json retry self-corrects on failure).

    The lookup is resolved through ``get_lookup`` rather than passed directly because the native
    tool-call path only knows which note was retrieved *after* the model's tool call executes, while
    the validators are handed to the client up front. The JSON path passes a constant getter.

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

    def require_grounding(fu: FollowUp) -> None:
        lookup = get_lookup()
        if lookup is None:
            return
        terms = _grounding_terms(lookup)
        if not terms:
            return
        candidate_text = _normalize(f"{fu.question} {fu.targets}")
        if not any(term in candidate_text for term in terms):
            raise ValueError(
                "the follow-up is not visibly grounded in the retrieved concept note — use a "
                "mechanism, failure mode, or term from lookup_concept in the question or targets"
            )

    return [reject_reask, require_grounding]


LOOKUP_CONCEPT_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "lookup_concept",
        "description": (
            "Retrieve the single most relevant concept note to ground a follow-up question. Apply "
            "the Skill/language metadata filters so Vietnamese notes are reachable without relying "
            "on an English embedder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Semantic query for the concept store."},
                "skill": {
                    "type": "string",
                    "description": "Optional Skill metadata filter. Use an empty string if no filter is needed.",
                },
                "language": {
                    "type": "string",
                    "description": "Optional language filter, e.g. 'vi'. Use an empty string if no filter is needed.",
                },
                "reason": {"type": "string", "description": "Why this lookup helps the follow-up."},
            },
            "required": ["query", "reason"],
        },
    },
}

NATIVE_TOOL_SYSTEM_PROMPT = (
    "You are the Interviewer in a mock technical interview. You never judge, score, or coach — a "
    "separate Evaluator does all judging. You have exactly one tool: lookup_concept(query, skill, "
    "language). First call lookup_concept exactly once to fetch the concept note that best grounds a "
    "question targeting the Evaluator's flagged gap. After you receive the note, write ONE follow-up "
    "question.\n\n"
    "Rules:\n"
    "- Call lookup_concept exactly once before you answer.\n"
    "- Use the Skill metadata filter when it is provided; this is mandatory for Vietnamese NLP notes.\n"
    "- Use language='vi' only when the target Skill or missing concept is Vietnamese-specific.\n"
    "- The follow-up MUST probe the flagged weakness — push for the missing mechanism, trade-off, or "
    "concrete detail — and MUST be materially shaped by the retrieved note.\n"
    "- It MUST NOT be answerable by simply repeating the original answer.\n"
    "- Ask exactly one focused question; no commentary."
)

_NATIVE_FINAL_INSTRUCTION = (
    "Now write the follow-up using the retrieved concept note. Respond with a single JSON object "
    f"only — no prose, no code fences — shaped like:\n{_FOLLOW_UP_SCHEMA_HINT}"
)


def _build_native_user(
    original_question: str,
    answer: str,
    evaluation: Evaluation,
    skill: str | None,
) -> str:
    return (
        f"ORIGINAL QUESTION:\n{original_question}\n\n"
        f"TARGET SKILL:\n{skill or 'unknown'}\n\n"
        f"CANDIDATE'S LATEST ANSWER:\n{answer}\n\n"
        f"EVALUATOR'S ASSESSMENT (weakest dimensions first):\n{_format_assessment(evaluation)}\n\n"
        "Call lookup_concept to fetch the most useful concept note, then write the follow-up."
    )


def _generate_follow_up_native(
    client: LLMClient,
    *,
    original_question: str,
    answer: str,
    evaluation: Evaluation,
    skill: str | None,
    store: ConceptStore,
) -> FollowUp:
    """Generate a Follow-up via a real provider-level tool call (one lookup_concept round-trip).

    The model emits a genuine ``tool_calls`` request; the ``execute`` callback runs it; the rendered
    note is fed back as a ``tool`` turn; then the model returns the schema-validated Follow-up. The
    same grounding gates apply — they read the retrieved note through the captured-lookup getter.
    """
    captured: dict[str, ConceptLookup] = {}

    def execute(name: str, args: dict[str, object]) -> str:
        if name != "lookup_concept":
            raise ValueError(f"interviewer received an unexpected tool call: {name!r}")
        request = ConceptToolRequest.model_validate({"reason": "tool call", **args})
        lookup_skill = skill or request.skill
        lookup_language = request.language or ("vi" if lookup_skill == "vietnamese_nlp" else None)
        lookup = lookup_concept(store, request.query, skill=lookup_skill, language=lookup_language)
        captured["lookup"] = lookup
        return lookup.render()

    messages = [
        {"role": "system", "content": NATIVE_TOOL_SYSTEM_PROMPT},
        {"role": "user", "content": _build_native_user(original_question, answer, evaluation, skill)},
    ]
    follow_up = client.chat_with_tools(
        messages,
        tools=[LOOKUP_CONCEPT_TOOL],
        tool_executor=execute,
        response_model=FollowUp,
        final_instruction=_NATIVE_FINAL_INSTRUCTION,
        validators=_make_validators(original_question, lambda: captured.get("lookup")),
        tool_choice={"type": "function", "function": {"name": "lookup_concept"}},
        max_retries=1,
        disable_thinking=True,
    )
    lookup = captured.get("lookup")
    if lookup is None:
        raise ToolCallingUnsupported("the model never executed lookup_concept")
    follow_up = follow_up.model_copy(
        update={"concept_id": lookup.note.id, "concept_title": lookup.note.title}
    )
    logger.info(
        "interviewer follow-up (native tool-call) targets %r using concept %r: %s",
        follow_up.targets,
        lookup.note.id,
        follow_up.question,
    )
    return follow_up


def _generate_follow_up_json(
    client: LLMClient,
    *,
    original_question: str,
    answer: str,
    evaluation: Evaluation,
    skill: str | None,
    store: ConceptStore,
) -> FollowUp:
    """Generate a Follow-up by emulating the tool call as two JSON turns (no native function-calling).

    Used only by non-native fake/dummy clients: the model plans the lookup as JSON, Python executes
    it, then the model writes the grounded Follow-up.
    """
    tool_request = client.chat_json(
        _build_tool_messages(original_question, answer, evaluation, skill),
        ConceptToolRequest,
        max_retries=1,
        disable_thinking=True,
    )
    lookup_skill = skill or tool_request.skill
    lookup_language = tool_request.language or ("vi" if lookup_skill == "vietnamese_nlp" else None)
    lookup = lookup_concept(
        store,
        tool_request.query,
        skill=lookup_skill,
        language=lookup_language,
    )
    follow_up = client.chat_json(
        _build_follow_up_messages(original_question, answer, evaluation, lookup),
        FollowUp,
        validators=_make_validators(original_question, lambda: lookup),
        max_retries=1,
        disable_thinking=True,
    )
    follow_up = follow_up.model_copy(
        update={
            "concept_id": lookup.note.id,
            "concept_title": lookup.note.title,
        }
    )
    logger.info(
        "interviewer follow-up targets %r using concept %r: %s",
        follow_up.targets,
        lookup.note.id,
        follow_up.question,
    )
    return follow_up


def generate_follow_up(
    client: LLMClient,
    *,
    original_question: str,
    answer: str,
    evaluation: Evaluation,
    skill: str | None = None,
    concept_store: ConceptStore | None = None,
) -> FollowUp:
    """Generate one grounded Follow-up using the Interviewer's lookup_concept tool.

    Uses a real provider-level tool call when the client supports it. Clients with no native tool
    interface can still use the JSON tool-plan path for offline fakes, but a native-tool provider
    that fails or declines the forced tool call is allowed to fail loudly; silently degrading would
    hide the exact integration issue this slice is meant to prove.
    """
    store = concept_store or seed_concept_store()
    if client.supports_tool_calls:
        return _generate_follow_up_native(
            client,
            original_question=original_question,
            answer=answer,
            evaluation=evaluation,
            skill=skill,
            store=store,
        )
    return _generate_follow_up_json(
        client,
        original_question=original_question,
        answer=answer,
        evaluation=evaluation,
        skill=skill,
        store=store,
    )
