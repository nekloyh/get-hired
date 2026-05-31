from __future__ import annotations

import pytest
from pydantic import BaseModel

from interview_coach.config import ProviderName, ProviderSettings, Settings
from interview_coach.llm import (
    GroqClient,
    LLMClient,
    LLMRouter,
    MimoClient,
    StructuredOutputError,
    ToolCallingUnsupported,
    build_client,
)


class Foo(BaseModel):
    x: int
    label: str


def _provider(name: ProviderName) -> ProviderSettings:
    return ProviderSettings(
        name=name,
        api_key="test",
        base_url=f"http://{name}.test",
        model=f"{name}-model",
    )


class _StaticClient(LLMClient):
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls += 1
        return self.reply


class _FailingClient(LLMClient):
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls += 1
        raise self.exc


def test_parses_valid_json(make_client):
    client, fake = make_client(['{"x": 7, "label": "ok"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out == Foo(x=7, label="ok")
    assert fake.call_count == 1


def test_retries_once_then_succeeds(make_client):
    client, fake = make_client(["not json at all", '{"x": 1, "label": "fixed"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.label == "fixed"
    assert fake.call_count == 2  # one retry


def test_raises_after_exhausting_retries(make_client):
    client, fake = make_client(["bad", "still bad"])
    with pytest.raises(StructuredOutputError):
        client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert fake.call_count == 2  # max_retries=1 -> 2 attempts total


def test_reasoning_content_is_ignored(make_client):
    client, _ = make_client([('{"x": 3, "label": "y"}', "<long chain-of-thought>")])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 3


def test_mimo_can_disable_thinking_for_tool_loops(make_client):
    client, fake = make_client(['{"x": 3, "label": "tool-loop"}'])
    out = client.chat_json(
        [{"role": "user", "content": "go"}],
        Foo,
        disable_thinking=True,
    )
    assert out.x == 3
    assert fake.chat.completions.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_mimo_and_groq_support_native_tool_calls(fake_openai_factory):
    mimo_client = MimoClient(_provider("mimo"), client=fake_openai_factory([]))
    groq_client = GroqClient(_provider("groq"), client=fake_openai_factory([]))

    assert mimo_client.supports_tool_calls is True
    assert groq_client.supports_tool_calls is True


def test_strips_code_fences(make_client):
    client, _ = make_client(['```json\n{"x": 5, "label": "z"}\n```'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 5


def test_extracts_json_wrapped_in_prose(make_client):
    client, _ = make_client(['Here you go: {"x": 9, "label": "w"} — done.'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 9


def test_empty_content_is_retried(make_client):
    client, fake = make_client(["", '{"x": 2, "label": "ok"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 2
    assert fake.call_count == 2


def test_custom_validator_triggers_retry(make_client):
    calls = {"n": 0}

    def reject_first(_foo: Foo) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("nope")

    client, fake = make_client(['{"x": 1, "label": "a"}', '{"x": 1, "label": "b"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo, validators=[reject_first])
    assert out.label == "b"
    assert fake.call_count == 2


def test_same_prompt_parses_with_mimo_and_groq(fake_openai_factory):
    prompt = [{"role": "user", "content": "Return the schema."}]
    reply = '{"x": 42, "label": "same-schema"}'
    mimo_client = MimoClient(_provider("mimo"), client=fake_openai_factory([reply]))
    groq_client = GroqClient(_provider("groq"), client=fake_openai_factory([reply]))

    assert mimo_client.chat_json(prompt, Foo) == Foo(x=42, label="same-schema")
    assert groq_client.chat_json(prompt, Foo) == Foo(x=42, label="same-schema")


def test_primary_provider_env_switches_to_groq(monkeypatch):
    monkeypatch.setenv("PRIMARY_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("GROQ_MODEL", "groq-model")

    settings = Settings(_env_file=None)

    assert settings.primary_provider == "groq"
    assert settings.primary_config.name == "groq"
    assert settings.configured


def test_build_client_returns_router_for_selected_primary():
    settings = Settings(
        _env_file=None,
        primary_provider="groq",
        groq_api_key="test",
        groq_model="groq-model",
    )

    client = build_client(settings)

    assert isinstance(client, LLMRouter)
    assert client.primary_provider == "groq"


def test_router_uses_selected_primary():
    mimo = _StaticClient('{"x": 1, "label": "mimo"}')
    groq = _StaticClient('{"x": 2, "label": "groq"}')
    router = LLMRouter("groq", {"mimo": mimo, "groq": groq})

    out = router.chat_json([{"role": "user", "content": "go"}], Foo)

    assert out == Foo(x=2, label="groq")
    assert groq.calls == 1
    assert mimo.calls == 0


def test_router_falls_back_on_primary_error():
    primary = _FailingClient(RuntimeError("boom"))
    fallback = _StaticClient('{"x": 3, "label": "fallback"}')
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    out = router.chat_json([{"role": "user", "content": "go"}], Foo)

    assert out == Foo(x=3, label="fallback")
    assert primary.calls == 1
    assert fallback.calls == 1


class _ToolClient(LLMClient):
    """A tool-capable client whose chat_with_tools outcome is scripted."""

    def __init__(self, *, declines: bool = False, error: Exception | None = None, result: str = "ok") -> None:
        self._declines = declines
        self._error = error
        self._result = result
        self.tool_calls = 0

    @property
    def supports_tool_calls(self) -> bool:
        return True

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        return ""

    def chat_with_tools(self, messages, **kwargs):
        self.tool_calls += 1
        if self._error is not None:
            raise self._error
        if self._declines:
            raise ToolCallingUnsupported("primary declined the forced tool call")
        return self._result


def _tool_kwargs() -> dict:
    return {"tools": [], "tool_executor": lambda name, args: "", "response_model": Foo, "final_instruction": "x"}


def test_router_tool_decline_propagates_without_failover():
    # A declined/unsupported native tool call must fail loudly — failing over would hide exactly the
    # tool-call integration problem this path exists to surface.
    primary = _ToolClient(declines=True)
    fallback = _ToolClient(result="groq")
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    with pytest.raises(ToolCallingUnsupported):
        router.chat_with_tools([{"role": "user", "content": "go"}], **_tool_kwargs())

    assert primary.tool_calls == 1
    assert fallback.tool_calls == 0  # NOT silently retried on the fallback


def test_router_tool_transport_error_fails_over():
    # A transport-level failure (timeout/5xx) is a real outage, so failover to a tool-capable
    # fallback is correct.
    primary = _ToolClient(error=RuntimeError("boom"))
    fallback = _ToolClient(result="groq-result")
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    out = router.chat_with_tools([{"role": "user", "content": "go"}], **_tool_kwargs())

    assert out == "groq-result"
    assert primary.tool_calls == 1
    assert fallback.tool_calls == 1
