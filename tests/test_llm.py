from __future__ import annotations

import httpx
import openai as openai_sdk
import pytest
from pydantic import BaseModel

from interview_coach import llm as llm_module
from interview_coach import telemetry
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
from interview_coach.usage import usage_for_day


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


# --- transport backoff + usage ledger (free-tier hardening) --------------------------------------


def _http_request() -> httpx.Request:
    return httpx.Request("POST", "http://test/v1/chat/completions")


def _rate_limited(message: str = "rate limited", headers: dict | None = None) -> Exception:
    return openai_sdk.RateLimitError(
        message, response=httpx.Response(429, headers=headers or {}, request=_http_request()), body=None
    )


def test_transport_backoff_retries_429_then_succeeds(monkeypatch, fake_openai_factory):
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    fake = fake_openai_factory([_rate_limited(), _rate_limited(), '{"x": 1, "label": "ok"}'])
    client = MimoClient(_provider("mimo"), client=fake)

    out = client.chat_json([{"role": "user", "content": "go"}], Foo)

    assert out.x == 1
    assert fake.call_count == 3
    assert waits == [2.0, 5.0]  # the fixed schedule when the provider sends no Retry-After
    assert telemetry.snapshot()["transport.backoff.mimo"] == 2


def test_transport_backoff_honors_retry_after_header(monkeypatch, fake_openai_factory):
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    fake = fake_openai_factory([_rate_limited(headers={"retry-after": "1"}), '{"x": 1, "label": "ok"}'])
    client = MimoClient(_provider("mimo"), client=fake)

    client.chat_json([{"role": "user", "content": "go"}], Foo)

    assert waits == [1.0]


def test_insufficient_quota_fails_fast_without_backoff(monkeypatch, fake_openai_factory):
    # When the DAY's allowance is spent, waiting cannot help — burn zero time and fail loudly.
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    fake = fake_openai_factory([_rate_limited(message="You exceeded your current quota: insufficient_quota")])
    client = MimoClient(_provider("mimo"), client=fake)

    with pytest.raises(openai_sdk.RateLimitError):
        client.chat([{"role": "user", "content": "go"}])

    assert fake.call_count == 1
    assert waits == []


def test_transport_backoff_gives_up_after_bounded_attempts(monkeypatch, fake_openai_factory):
    monkeypatch.setattr(llm_module, "_sleep", lambda _wait: None)
    fake = fake_openai_factory([_rate_limited()])  # the fake repeats its last scripted reply
    client = MimoClient(_provider("mimo"), client=fake)

    with pytest.raises(openai_sdk.RateLimitError):
        client.chat([{"role": "user", "content": "go"}])

    assert fake.call_count == llm_module._TRANSPORT_ATTEMPTS


def test_5xx_is_retried_but_4xx_is_not(monkeypatch, fake_openai_factory):
    monkeypatch.setattr(llm_module, "_sleep", lambda _wait: None)
    server_err = openai_sdk.InternalServerError(
        "boom", response=httpx.Response(500, request=_http_request()), body=None
    )
    fake = fake_openai_factory([server_err, '{"x": 2, "label": "recovered"}'])
    client = MimoClient(_provider("mimo"), client=fake)
    assert client.chat_json([{"role": "user", "content": "go"}], Foo).x == 2
    assert fake.call_count == 2

    bad_request = openai_sdk.BadRequestError(
        "bad", response=httpx.Response(400, request=_http_request()), body=None
    )
    fake2 = fake_openai_factory([bad_request])
    client2 = MimoClient(_provider("mimo"), client=fake2)
    with pytest.raises(openai_sdk.BadRequestError):
        client2.chat([{"role": "user", "content": "go"}])
    assert fake2.call_count == 1


def test_usage_recorded_to_daily_ledger(monkeypatch, tmp_path, fake_openai_factory):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    fake = fake_openai_factory(
        [{"content": '{"x": 1, "label": "ok"}', "usage": {"prompt_tokens": 100, "completion_tokens": 20}}]
    )
    client = MimoClient(_provider("mimo"), client=fake)

    client.chat_json([{"role": "user", "content": "go"}], Foo)

    totals = usage_for_day()
    assert totals["mimo"] == {"prompt": 100, "completion": 20, "total": 120, "calls": 1}


def test_sdk_retries_disabled_so_backoff_is_singly_owned(monkeypatch):
    captured: dict = {}

    class _RecordingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "OpenAI", _RecordingOpenAI)
    GroqClient(_provider("groq"))._openai()
    assert captured["max_retries"] == 0


# --- strict json_schema constrained decoding (probed live on gpt-5.4-mini 2026-07-11) ------------


def _openai_client(fake):
    from interview_coach.llm import OpenAIClient

    return OpenAIClient(_provider("openai"), client=fake)


TINY_SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "label": {"type": "string"}},
    "required": ["x", "label"],
    "additionalProperties": False,
}


def test_json_schema_sent_as_strict_grammar_on_supporting_client(fake_openai_factory):
    fake = fake_openai_factory(['{"x": 1, "label": "ok"}'])
    client = _openai_client(fake)

    client.chat_json([{"role": "user", "content": "go"}], Foo, json_schema=TINY_SCHEMA)

    sent = fake.chat.completions.calls[0]["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["name"] == "foo"
    assert sent["json_schema"]["strict"] is True
    assert sent["json_schema"]["schema"] == TINY_SCHEMA


def test_json_schema_ignored_on_unsupporting_client(fake_openai_factory):
    fake = fake_openai_factory(['{"x": 1, "label": "ok"}'])
    client = MimoClient(_provider("mimo"), client=fake)  # MiMo: not verified, opted out

    client.chat_json([{"role": "user", "content": "go"}], Foo, json_schema=TINY_SCHEMA)

    assert fake.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_router_downgrades_grammar_for_schema_less_fallback(fake_openai_factory):
    from interview_coach.llm import OpenAIClient

    # Primary (openai, grammar-capable) dies; fallback (mimo) cannot enforce the grammar. The
    # failover must downgrade to json_object rather than turn an outage into a 400.
    fake_primary = fake_openai_factory([_rate_limited(message="quota: insufficient_quota")])
    fake_fallback = fake_openai_factory(['{"x": 9, "label": "fallback"}'])
    router = LLMRouter(
        "openai",
        {
            "openai": OpenAIClient(_provider("openai"), client=fake_primary),
            "mimo": MimoClient(_provider("mimo"), client=fake_fallback),
        },
        fallback_provider="mimo",
    )

    out = router.chat_json([{"role": "user", "content": "go"}], Foo, json_schema=TINY_SCHEMA)

    assert out.x == 9
    assert fake_primary.chat.completions.calls[0]["response_format"]["type"] == "json_schema"
    assert fake_fallback.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_408_and_409_stay_retryable_after_sdk_retries_disabled(monkeypatch, fake_openai_factory):
    # max_retries=0 moved retry ownership from the SDK to _create(); the SDK's default policy
    # retried 408/409, so ours must too or hardening would silently narrow recovery.
    monkeypatch.setattr(llm_module, "_sleep", lambda _wait: None)
    timeout_408 = openai_sdk.APIStatusError(
        "timeout", response=httpx.Response(408, request=_http_request()), body=None
    )
    fake = fake_openai_factory([timeout_408, '{"x": 4, "label": "recovered"}'])
    client = MimoClient(_provider("mimo"), client=fake)
    assert client.chat_json([{"role": "user", "content": "go"}], Foo).x == 4
    assert fake.call_count == 2
