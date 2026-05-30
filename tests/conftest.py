"""Test helpers: a minimal fake OpenAI client that scripts successive chat replies.

The fake stands in for ``openai.OpenAI`` and is injected into a real :class:`MimoClient`, so the
retry/validation logic in ``chat_json`` is exercised end-to-end against canned model output.
"""

from __future__ import annotations

import pytest

from interview_coach.config import Settings
from interview_coach.llm import MimoClient


class _FakeMessage:
    def __init__(self, content: str, reasoning_content: str | None = None) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.model_extra = {"reasoning_content": reasoning_content} if reasoning_content else {}


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
        content, reasoning = reply if isinstance(reply, tuple) else (reply, None)
        return _FakeResponse(_FakeMessage(content, reasoning))


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
    return Settings(_env_file=None, api_key="test", base_url="http://test", model="test-model")


@pytest.fixture
def make_client(settings: Settings):
    def _make(replies: list) -> tuple[MimoClient, FakeOpenAI]:
        fake = FakeOpenAI(replies)
        return MimoClient(settings, client=fake), fake

    return _make
