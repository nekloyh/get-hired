"""Offline smoke test for issue 0007's native tool-using Interviewer.

This does not hit a real provider. It injects a fake OpenAI-compatible MiMo client that returns one
native ``tool_calls`` turn, then a final JSON Follow-up. The smoke proves the wiring that matters for
ADR 0003:

- only the Interviewer invokes tools;
- MiMo thinking is disabled on the tool loop;
- ``reasoning_content`` is not replayed into the multi-turn tool history;
- lookup_concept is executed and the retrieved note grounds the Follow-up.
"""

from __future__ import annotations

import json
from typing import Any

from interview_coach.concepts import InMemoryConceptStore, seed_concept_store
from interview_coach.config import ProviderSettings
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.interviewer import generate_follow_up
from interview_coach.llm import LLMRouter, MimoClient


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.id = "call_lookup_1"
        self.type = "function"
        self.function = _FakeFunction(name, json.dumps(arguments))


class _FakeMessage:
    def __init__(
        self,
        *,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.model_extra = {"reasoning_content": reasoning_content} if reasoning_content else {}
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return _FakeResponse(
                _FakeMessage(
                    reasoning_content="<provider-internal thinking that must not be replayed>",
                    tool_calls=[
                        _FakeToolCall(
                            "lookup_concept",
                            {
                                "query": "L2 penalty variance mechanism",
                                "skill": "ml_fundamentals",
                                "language": None,
                                "reason": "The answer mentions smaller weights without the variance mechanism.",
                            },
                        )
                    ],
                )
            )
        return _FakeResponse(
            _FakeMessage(
                content=json.dumps(
                    {
                        "question": "What mechanism connects the L2 penalty to lower variance?",
                        "targets": "depth: penalty-to-variance mechanism",
                    }
                )
            )
        )


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeOpenAI:
    def __init__(self) -> None:
        self.chat = _FakeChat()


def _weak_evaluation() -> Evaluation:
    return Evaluation(
        dimensions={
            "correctness": DimensionScore(score=3, evidence="no evidence"),
            "depth": DimensionScore(score=2, evidence="smaller weights"),
        },
        weighted_score=2.5,
        confidence=0.7,
        follow_up_recommended=True,
        follow_up_rationale="The answer never connects the penalty to variance reduction.",
    )


def main() -> int:
    fake = _FakeOpenAI()
    mimo = MimoClient(
        ProviderSettings(
            name="mimo",
            api_key="smoke",
            base_url="http://mimo-smoke.test",
            model="mimo-smoke-model",
        ),
        client=fake,
    )
    client = LLMRouter("mimo", {"mimo": mimo})
    store = seed_concept_store(InMemoryConceptStore())

    follow_up = generate_follow_up(
        client,
        original_question="Why does L2 regularization reduce overfitting?",
        answer="It makes the weights smaller which is better.",
        evaluation=_weak_evaluation(),
        skill="ml_fundamentals",
        concept_store=store,
    )

    calls = fake.chat.completions.calls
    assert len(calls) == 2
    assert calls[0]["tools"][0]["function"]["name"] == "lookup_concept"
    assert calls[0]["tool_choice"]["function"]["name"] == "lookup_concept"
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert any(m.get("role") == "tool" and "L2 regularization" in m.get("content", "") for m in calls[1]["messages"])
    assert all("reasoning_content" not in m for m in calls[1]["messages"])
    assert follow_up.concept_id == "ml_fundamentals_l2_regularization"
    assert "penalty" in follow_up.question.lower()
    assert store.lookup_calls == [
        {"query": "L2 penalty variance mechanism", "skill": "ml_fundamentals", "language": None}
    ]

    print("issue 0007 smoke: PASS")
    print(f"- native provider tool calls: {calls[0]['tools'][0]['function']['name']}")
    print("- MiMo thinking disabled on both tool-loop requests")
    print("- reasoning_content not replayed")
    print(f"- grounded concept: {follow_up.concept_id}")
    print(f"- follow-up: {follow_up.question}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
