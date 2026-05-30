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

    def chat(self, messages, *, response_format=None) -> str:
        self.calls += 1
        return self.reply


class _FailingClient(LLMClient):
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def chat(self, messages, *, response_format=None) -> str:
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
