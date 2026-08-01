"""Test helpers: a minimal fake OpenAI-compatible client that scripts successive chat replies.

The fake stands in for ``openai.OpenAI`` and is injected into real provider clients, so the
retry/validation logic in ``chat_json`` is exercised end-to-end against canned model output.
"""

from __future__ import annotations

import json
import os

import pytest

from interview_coach import telemetry
from interview_coach.config import ProviderSettings, Settings
from interview_coach.llm import GroqClient, LLMRouter, MimoClient

# At conftest import, not in a fixture, and deliberately: `interview_coach.web_api` runs
# `guard_single_worker()` at module scope, and that import happens during *collection* — an autouse
# fixture runs far too late. A developer with WEB_CONCURRENCY exported for some other project would
# otherwise get "Interrupted: 1 error during collection" and zero of the tests, from a variable that
# has nothing to do with this repo. The guard's real call site is still pinned, in a subprocess with
# WEB_CONCURRENCY set explicitly (tests/test_web_api.py).
os.environ.pop("WEB_CONCURRENCY", None)


@pytest.fixture(autouse=True)
def _reset_telemetry():
    """Noise counters are process-global; every test starts from a clean slate."""
    telemetry.reset()
    yield


@pytest.fixture(autouse=True)
def _restore_coach_log_file():
    """`_cmd_api` writes COACH_LOG_FILE into os.environ on purpose, so a test cannot just delenv it.

    ``monkeypatch.delenv(..., raising=False)`` records no undo when the variable was absent, so the
    value a CLI test causes to be *created* survives into every later test in the session — where it
    would attach a file handler pointing at a deleted tmp_path.
    """
    saved = os.environ.get("COACH_LOG_FILE")
    os.environ.pop("COACH_LOG_FILE", None)
    yield
    if saved is None:
        os.environ.pop("COACH_LOG_FILE", None)
    else:
        os.environ["COACH_LOG_FILE"] = saved


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


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, message: _FakeMessage, usage: _FakeUsage | None = None) -> None:
        self.choices = [_FakeChoice(message)]
        self.usage = usage


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
        if isinstance(reply, dict) and "usage" in reply:
            # A scripted reply carrying token usage: exercises the client-side daily ledger.
            usage = _FakeUsage(reply["usage"]["prompt_tokens"], reply["usage"]["completion_tokens"])
            return _FakeResponse(_FakeMessage(content=reply.get("content", "")), usage=usage)
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
