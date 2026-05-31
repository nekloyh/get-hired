"""Test helpers: a minimal fake OpenAI-compatible client that scripts successive chat replies.

The fake stands in for ``openai.OpenAI`` and is injected into real provider clients, so the
retry/validation logic in ``chat_json`` is exercised end-to-end against canned model output.
"""

from __future__ import annotations

import json

import pytest

from interview_coach.config import ProviderSettings, Settings
from interview_coach.llm import GroqClient, LLMRouter, MimoClient


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(
        self,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list | None = None,
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
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict) and "tool_calls" in reply:
            # A scripted native function-call turn: emit a message carrying tool_calls.
            calls = [
                _FakeToolCall(
                    tc.get("id", f"call_{i}"),
                    tc["name"],
                    tc["arguments"] if isinstance(tc["arguments"], str) else json.dumps(tc["arguments"]),
                )
                for i, tc in enumerate(reply["tool_calls"])
            ]
            return _FakeResponse(_FakeMessage(content=reply.get("content"), tool_calls=calls))
        content, reasoning = reply if isinstance(reply, tuple) else (reply, None)
        return _FakeResponse(_FakeMessage(content=content, reasoning_content=reasoning))


class _FakeChat:
    def __init__(self, replies: list) -> None:
        self.completions = _FakeCompletions(replies)


class FakeOpenAI:
    """Scripts a list of replies; each is a JSON string or a (content, reasoning_content) tuple."""

    def __init__(self, replies: list) -> None:
        self.chat = _FakeChat(replies)

    @property
    def call_count(self) -> int:
        return len(self.chat.completions.calls)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="test",
        mimo_base_url="http://test",
        mimo_model="test-model",
    )


@pytest.fixture
def fake_openai_factory():
    return FakeOpenAI


@pytest.fixture
def make_client(settings: Settings):
    def _make(replies: list) -> tuple[LLMRouter, FakeOpenAI]:
        fake = FakeOpenAI(replies)
        mimo = MimoClient(settings.provider_config("mimo"), client=fake)
        return LLMRouter("mimo", {"mimo": mimo}), fake

    return _make


@pytest.fixture
def make_tool_client():
    """A router whose primary (Groq) does native function-calling — exercises the real tool path."""

    def _make(replies: list) -> tuple[LLMRouter, FakeOpenAI]:
        fake = FakeOpenAI(replies)
        groq = GroqClient(
            ProviderSettings(name="groq", api_key="test", base_url="http://groq.test", model="groq-model"),
            client=fake,
        )
        return LLMRouter("groq", {"groq": groq}), fake

    return _make
