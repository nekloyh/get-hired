from __future__ import annotations

import json

import pytest

from interview_coach.concepts import ConceptNote, InMemoryConceptStore
from interview_coach.config import load_settings
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.interviewer import FollowUp, FollowUpUnavailable, generate_follow_up
from interview_coach.llm import LLMClient, ToolCallingUnsupported, build_client

_CONCEPT = ConceptNote(
    id="l2",
    skill="ml_fundamentals",
    title="L2 penalty and variance",
    content="The L2 penalty shrinks weights, smoothing the learned function and reducing variance.",
    tags=("regularization", "variance", "penalty"),
)


def _store() -> InMemoryConceptStore:
    return InMemoryConceptStore([_CONCEPT])


def _tool_json(
    query: str = "L2 penalty variance mechanism",
    skill: str | None = "ml_fundamentals",
    language: str | None = None,
) -> str:
    return json.dumps(
        {
            "query": query,
            "skill": skill,
            "language": language,
            "reason": "The answer mentions smaller weights but not the penalty-to-variance mechanism.",
        }
    )


def _followup_json(
    question: str = "What mechanism connects the L2 penalty to lower variance?",
    targets: str = "depth: penalty-to-variance mechanism",
) -> str:
    return json.dumps({"question": question, "targets": targets})


def _weak_evaluation(rationale: str = "the answer never explains the mechanism") -> Evaluation:
    return Evaluation(
        dimensions={
            "correctness": DimensionScore(score=3, evidence="no evidence"),
            "depth": DimensionScore(score=2, evidence="it makes the weights smaller"),
        },
        weighted_score=2.5,
        confidence=0.7,
        follow_up_recommended=True,
        follow_up_rationale=rationale,
    )


def test_generate_follow_up_returns_structured(make_client):
    store = _store()
    client, fake = make_client([_tool_call_reply(), _followup_json()])
    fu = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes the weights smaller which is better.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=store,
    )
    assert isinstance(fu, FollowUp)
    assert fu.question and fu.targets
    assert fu.concept_id == "l2"
    assert fu.concept_title == "L2 penalty and variance"
    assert fu.concept_score is not None
    assert fu.concept_lookup_query == "L2 penalty variance mechanism"
    assert fu.concept_lookup_skill == "ml_fundamentals"
    assert fu.concept_lookup_language is None
    assert fake.call_count == 2
    assert store.lookup_calls == [
        {"query": "L2 penalty variance mechanism", "skill": "ml_fundamentals", "language": None}
    ]


def test_follow_up_prompt_targets_the_gap(make_client):
    # The follow-up must target the gap, not re-ask the question — so the Interviewer is fed the
    # candidate's answer and the Evaluator's rationale + weak dimensions. Assert they reach the prompt.
    client, fake = make_client([_tool_call_reply(), _followup_json()])
    answer = "It makes the weights smaller which is better."
    generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer=answer,
        evaluation=_weak_evaluation(rationale="the answer never explains the mechanism"),
        skill="ml_fundamentals",
        concept_store=_store(),
    )
    user_msg = fake.chat.completions.calls[0]["messages"][-1]["content"]
    assert answer in user_msg  # the Interviewer sees what was actually said...
    assert "the answer never explains the mechanism" in user_msg  # ...and where it fell short
    assert "depth: 2/5" in user_msg  # the weakest dimension is surfaced (weakest-first ordering)
    final_messages = fake.chat.completions.calls[1]["messages"]
    assert any(
        m.get("role") == "tool" and "The L2 penalty shrinks weights" in m.get("content", "")
        for m in final_messages
    )


def test_weakest_dimension_is_listed_first(make_client):
    client, fake = make_client([_tool_call_reply(), _followup_json()])
    generate_follow_up(
        client,
        original_question="q",
        answer="a",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=_store(),
    )
    user_msg = fake.chat.completions.calls[0]["messages"][-1]["content"]
    # depth (2/5) must appear before correctness (3/5): the gap leads.
    assert user_msg.index("depth: 2/5") < user_msg.index("correctness: 3/5")


def test_generate_follow_up_rejects_reasking_original_question(make_client):
    # A follow-up that just restates the original question is answerable by repeating the original
    # answer — the acceptance criterion forbids it. The validator must reject it and retry.
    original = "Why does L2 regularization reduce overfitting?"
    client, fake = make_client(
        [
            _tool_call_reply(),
            _followup_json(question=original, targets="generic repeat"),
            _followup_json(
                question="What mechanism connects the L2 penalty to lower variance?",
                targets="depth: mechanism",
            ),
        ]
    )

    fu = generate_follow_up(
        client,
        original_question=original,
        answer="It makes weights smaller.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=_store(),
    )

    assert fu.question == "What mechanism connects the L2 penalty to lower variance?"
    assert fake.call_count == 3


def test_interviewer_disables_mimo_thinking_for_tool_loop(make_client):
    client, fake = make_client([_tool_call_reply(), _followup_json()])

    generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes weights smaller.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=_store(),
    )

    assert [call["extra_body"] for call in fake.chat.completions.calls] == [
        {"thinking": {"type": "disabled"}},
        {"thinking": {"type": "disabled"}},
    ]


def _tool_call_reply(
    query: str = "L2 penalty variance mechanism",
    skill: str | None = "ml_fundamentals",
    language: str | None = None,
) -> dict:
    return {
        "tool_calls": [
            {
                "name": "lookup_concept",
                "arguments": {
                    "query": query,
                    "skill": skill,
                    "language": language,
                    "reason": "probe the penalty-to-variance mechanism",
                },
            }
        ]
    }


def test_generate_follow_up_uses_native_tool_call(make_tool_client):
    # On a tool-capable provider the lookup is a real provider-level tool call: the first turn
    # carries tools + a forced tool_choice, and the retrieved note is fed back as a `tool` turn
    # before the model writes the (still schema-validated) follow-up.
    store = _store()
    client, fake = make_tool_client([_tool_call_reply(), _followup_json()])

    fu = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes the weights smaller which is better.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=store,
    )

    assert isinstance(fu, FollowUp)
    assert fu.concept_id == "l2"
    first_call = fake.chat.completions.calls[0]
    assert first_call["tools"][0]["function"]["name"] == "lookup_concept"
    assert first_call["tool_choice"]["function"]["name"] == "lookup_concept"
    final_messages = fake.chat.completions.calls[1]["messages"]
    assert any(m.get("role") == "tool" for m in final_messages)  # tool result was replayed
    assert store.lookup_calls == [
        {"query": "L2 penalty variance mechanism", "skill": "ml_fundamentals", "language": None}
    ]


def _garbled_tool_reply(name: str = "lookup_concpet") -> dict:
    # A misspelled/garbled tool name — the transient MiMo glitch that used to crash the whole Session.
    return {
        "tool_calls": [
            {
                "name": name,
                "arguments": {
                    "query": "L2 penalty variance mechanism",
                    "skill": "ml_fundamentals",
                    "language": None,
                    "reason": "probe the penalty-to-variance mechanism",
                },
            }
        ]
    }


def test_garbled_tool_name_is_retried_then_recovers(make_tool_client):
    # A garbled tool name is a transient blip, not an integration failure: retry the round-trip once,
    # and when the retry yields a valid lookup_concept call the follow-up still succeeds.
    store = _store()
    client, fake = make_tool_client([_garbled_tool_reply(), _tool_call_reply(), _followup_json()])

    fu = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes the weights smaller which is better.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=store,
    )

    assert isinstance(fu, FollowUp)
    assert fu.concept_id == "l2"  # the retried, valid tool call actually retrieved the note
    assert fake.call_count == 3  # garbled round-trip, retried round-trip, final follow-up
    assert store.lookup_calls == [
        {"query": "L2 penalty variance mechanism", "skill": "ml_fundamentals", "language": None}
    ]


def test_garbled_tool_name_that_persists_degrades_not_crashes(make_tool_client):
    # If the garbled name survives the one retry, raise FollowUpUnavailable — a recoverable degrade
    # signal the micro-loop catches — NOT ToolCallingUnsupported, which is reserved for genuine
    # tool-calling integration failures that must stay loud (ADR 0003).
    assert not issubclass(FollowUpUnavailable, ToolCallingUnsupported)
    store = _store()
    client, fake = make_tool_client([_garbled_tool_reply()])  # clamped: every round-trip is garbled

    with pytest.raises(FollowUpUnavailable):
        generate_follow_up(
            client,
            original_question="Why does L2 regularization reduce overfitting?",
            answer="It makes weights smaller.",
            evaluation=_weak_evaluation(),
            skill="ml_fundamentals",
            concept_store=store,
        )

    assert fake.call_count == 2  # one attempt + one retry, both garbled
    assert store.lookup_calls == []  # the garbled name never reached lookup_concept


def test_missing_concept_note_degrades_on_native_path(make_tool_client):
    # lookup_concept finds no note for the requested Skill: the question must degrade to no follow-up
    # (FollowUpUnavailable) rather than crash (slice 0014). Crucially the miss is NOT raised out of the
    # tool executor — that would surface to the provider router as a transport fault and trip a
    # spurious failover — so the round-trip completes and the degrade is raised afterwards.
    store = _store()  # only an ml_fundamentals note exists
    client, fake = make_tool_client([_tool_call_reply(skill="mlops"), _followup_json()])

    with pytest.raises(FollowUpUnavailable):
        generate_follow_up(
            client,
            original_question="How do you monitor data drift in production?",
            answer="You just retrain sometimes.",
            evaluation=_weak_evaluation(),
            skill="mlops",
            concept_store=store,
        )

    assert fake.call_count == 2  # the tool round-trip + the final structured turn both ran
    assert store.lookup_calls == [
        {"query": "L2 penalty variance mechanism", "skill": "mlops", "language": None}
    ]


def test_missing_concept_note_degrades_on_json_path():
    # The non-native JSON path degrades the same way: a concept miss raises FollowUpUnavailable before
    # the follow-up is generated, so the micro-loop keeps the last score instead of crashing.
    store = _store()
    client = _JsonOnlyClient([_tool_json(skill="mlops")])

    with pytest.raises(FollowUpUnavailable):
        generate_follow_up(
            client,
            original_question="How do you monitor data drift in production?",
            answer="You just retrain sometimes.",
            evaluation=_weak_evaluation(),
            skill="mlops",
            concept_store=store,
        )

    assert len(client.calls) == 1  # the tool-plan call ran; the follow-up call never happens
    assert store.lookup_calls == [
        {"query": "L2 penalty variance mechanism", "skill": "mlops", "language": None}
    ]


def test_native_declined_fails_loudly(make_tool_client):
    # If a native-tool provider declines the forced tool call, do not hide it behind the JSON
    # fallback: this slice is specifically proving provider-level tool-calling.
    store = _store()
    client, fake = make_tool_client(["no tool call here", _tool_json(), _followup_json()])

    with pytest.raises(ToolCallingUnsupported):
        generate_follow_up(
            client,
            original_question="Why does L2 regularization reduce overfitting?",
            answer="It makes weights smaller.",
            evaluation=_weak_evaluation(),
            skill="ml_fundamentals",
            concept_store=store,
        )

    assert fake.call_count == 1
    assert store.lookup_calls == []


class _JsonOnlyClient(LLMClient):
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls.append(
            {
                "messages": messages,
                "response_format": response_format,
                "disable_thinking": disable_thinking,
            }
        )
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


def test_json_tool_plan_fallback_is_only_for_non_native_clients():
    store = _store()
    client = _JsonOnlyClient([_tool_json(), _followup_json()])

    fu = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes weights smaller.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=store,
    )

    assert fu.concept_id == "l2"
    assert len(client.calls) == 2
    assert all(call["disable_thinking"] is True for call in client.calls)


@pytest.mark.live
def test_live_interviewer_uses_lookup_concept_tool():
    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM primary provider not configured — set PRIMARY_PROVIDER and provider credentials")
    client = build_client(settings)
    store = _store()

    fu = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes weights smaller.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=store,
    )

    assert fu.concept_id == "l2"
    assert store.lookup_calls, "lookup_concept was not executed"
    assert fu.question.strip()


# --- language preference decoupled from the shelf + graceful widening (issue 0008 follow-up) -----


def test_preferred_lookup_language_derivation():
    from interview_coach.interviewer import _preferred_lookup_language

    # The model's own request wins.
    assert _preferred_lookup_language("vi", "mlops", "en") == "vi"
    # A vn/mixed Session prefers vi notes on ANY shelf — pre-fix this was vietnamese_nlp-only.
    assert _preferred_lookup_language(None, "ml_fundamentals", "vn") == "vi"
    assert _preferred_lookup_language(None, "system_design", "mixed") == "vi"
    # The vi-native shelf keeps its default in an en Session.
    assert _preferred_lookup_language(None, "vietnamese_nlp", "en") == "vi"
    assert _preferred_lookup_language(None, "mlops", "en") is None


def test_lookup_widens_to_any_language_when_shelf_has_no_vi_notes():
    from interview_coach.concepts import InMemoryConceptStore
    from interview_coach.interviewer import _lookup_with_widening

    store = InMemoryConceptStore(
        [ConceptNote(id="en_note", skill="mlops", title="drift", content="drift monitoring")]
    )

    lookup, applied = _lookup_with_widening(store, "drift", skill="mlops", language="vi")

    assert lookup.note.id == "en_note"  # vi preference widened instead of failing the follow-up
    assert applied is None  # the recorded filter reflects what actually ran
    assert store.lookup_calls[-1]["language"] is None


def test_lookup_keeps_language_filter_when_it_matches():
    from interview_coach.concepts import InMemoryConceptStore
    from interview_coach.interviewer import _lookup_with_widening

    store = InMemoryConceptStore(
        [
            ConceptNote(id="vi_note", skill="mlops", title="giám sát drift", content="nội dung", language="vi"),
            ConceptNote(id="en_note", skill="mlops", title="drift", content="drift monitoring"),
        ]
    )

    lookup, applied = _lookup_with_widening(store, "drift", skill="mlops", language="vi")

    assert lookup.note.id == "vi_note"
    assert applied == "vi"


def test_lookup_without_language_preference_raises_on_empty_shelf():
    import pytest as _pytest

    from interview_coach.concepts import InMemoryConceptStore
    from interview_coach.interviewer import _lookup_with_widening

    store = InMemoryConceptStore([])
    with _pytest.raises(LookupError):
        _lookup_with_widening(store, "q", skill="mlops", language=None)
