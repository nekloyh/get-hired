from __future__ import annotations

import logging

import httpx
import openai as openai_sdk
import pytest
from pydantic import BaseModel

from interview_coach import llm as llm_module
from interview_coach import telemetry, usage
from interview_coach.config import ProviderName, ProviderSettings, Settings
from interview_coach.llm import (
    BREAKER_COOLDOWN_SECONDS,
    BREAKER_FAILURE_THRESHOLD,
    CALL_LOG_PREFIX,
    RAW_OUTPUT_LOG_CHARS,
    EmptyCompletionError,
    GroqClient,
    LLMClient,
    LLMConfigurationError,
    LLMRouter,
    MimoClient,
    StructuredOutputError,
    ToolCallingUnsupported,
    build_client,
    call_counts,
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
    def __init__(self, reply: str, *, supports_json_schema: bool = True) -> None:
        self.reply = reply
        self.calls = 0
        self.formats: list[object] = []  # every response_format it was handed, in order
        self._supports_json_schema = supports_json_schema

    @property
    def supports_json_schema(self) -> bool:
        return self._supports_json_schema

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls += 1
        self.formats.append(response_format)
        return self.reply


class _FailingClient(LLMClient):
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls += 1
        raise self.exc


class _SwitchableClient(LLMClient):
    """A client whose failure can be turned off mid-test — for probing breaker recovery."""

    def __init__(self, exc: Exception | None) -> None:
        self.exc = exc
        self.calls = 0

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return "primary-answer"


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
    # A real transport failure — since R-09 the failover predicate is typed, and a bare RuntimeError
    # (which this test used to pass) is now correctly treated as OUR bug, not the provider's.
    primary = _FailingClient(openai_sdk.APIConnectionError(request=_http_request()))
    fallback = _StaticClient('{"x": 3, "label": "fallback"}')
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    out = router.chat_json([{"role": "user", "content": "go"}], Foo)

    assert out == Foo(x=3, label="fallback")
    assert primary.calls == 1
    assert fallback.calls == 1


# --- R-26: per-call trace + call accounting -----------------------------------------------------


def test_every_call_is_counted_per_provider(make_client):
    telemetry.reset()
    client, _ = make_client(['{"x": 1, "label": "a"}'])
    before = telemetry.snapshot()
    client.chat([{"role": "user", "content": "go"}])
    client.chat([{"role": "user", "content": "go"}])

    total, per_provider = call_counts(before, telemetry.snapshot())
    assert total == 2
    assert per_provider == (("mimo", 2),)


def test_retries_and_failures_are_counted_as_the_calls_they_are(make_client):
    # A structured-output retry is a second real provider call. Counting only "logical" calls would
    # under-report exactly the case the issue is about (<=8 judge calls per answer).
    telemetry.reset()
    client, fake = make_client(["not json at all", '{"x": 1, "label": "fixed"}'])
    before = telemetry.snapshot()
    client.chat_json([{"role": "user", "content": "go"}], Foo)

    total, _ = call_counts(before, telemetry.snapshot())
    assert fake.call_count == 2
    assert total == 2


def test_call_counts_ignores_unrelated_telemetry_movement():
    before = {"llm.calls": 1, "llm.calls.mimo": 1, "sanitizer.whatever": 5}
    after = {"llm.calls": 4, "llm.calls.mimo": 1, "llm.calls.groq": 2, "sanitizer.whatever": 9}

    total, per_provider = call_counts(before, after)

    assert total == 3
    assert per_provider == (("groq", 2),)  # mimo did not move, so it is not in this turn's split


def test_per_call_line_carries_provider_model_latency_tokens_and_outcome(make_client, caplog, tmp_path, monkeypatch):
    # The scripted `usage` block makes this the one trace test that also writes a ledger row; without
    # a tmp ledger it lands in the repo's real logs/usage-ledger.jsonl. That was cosmetic when the
    # ledger only fed a printed warning — R-25 turned it into a rail that REFUSES Sessions, so test
    # spend must never count against a real day's budget.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "usage-ledger.jsonl"))
    client, _ = make_client(
        [{"content": '{"x": 1, "label": "a"}', "usage": {"prompt_tokens": 11, "completion_tokens": 7}}]
    )
    with caplog.at_level(logging.INFO, logger="interview_coach.llm"):
        client.chat([{"role": "user", "content": "go"}])

    line = next(m for m in caplog.messages if m.startswith(CALL_LOG_PREFIX))
    assert "provider=mimo" in line
    assert "model=test-model" in line
    assert "prompt=11" in line
    assert "completion=7" in line
    assert "outcome=ok" in line
    assert "ms=" in line


def test_a_failed_call_still_emits_its_trace_line(make_client, caplog):
    # The failing call is the one worth tracing; a trace that only records successes is useless for
    # diagnosing an outage.
    client, _ = make_client(
        [openai_sdk.AuthenticationError("nope", response=httpx.Response(401, request=_http_request()), body=None)]
    )
    with caplog.at_level(logging.INFO, logger="interview_coach.llm"), pytest.raises(openai_sdk.AuthenticationError):
        client.chat([{"role": "user", "content": "go"}])

    line = next(m for m in caplog.messages if m.startswith(CALL_LOG_PREFIX))
    assert "outcome=error:AuthenticationError" in line


def test_a_backed_off_retry_is_traced_as_a_retry(make_client, caplog, monkeypatch):
    monkeypatch.setattr(llm_module, "_sleep", lambda _s: None)
    client, _ = make_client(
        [
            openai_sdk.APIStatusError("boom", response=httpx.Response(503, request=_http_request()), body=None),
            '{"x": 1, "label": "recovered"}',
        ]
    )
    with caplog.at_level(logging.INFO, logger="interview_coach.llm"):
        client.chat([{"role": "user", "content": "go"}])

    outcomes = [m.split("outcome=")[1] for m in caplog.messages if m.startswith(CALL_LOG_PREFIX)]
    assert outcomes == ["retry:APIStatusError", "ok"]


def test_structured_output_failure_logs_the_raw_reply(make_client, caplog):
    # Prose, a code fence, a truncated object and a refusal all surface identically as
    # "could not obtain schema-valid output"; the raw reply is what tells them apart.
    junk = "I'm sorry, I cannot comply with that request. " * 40
    client, _ = make_client([junk])
    with caplog.at_level(logging.ERROR, logger="interview_coach.llm"), pytest.raises(StructuredOutputError):
        client.chat_json([{"role": "user", "content": "go"}], Foo, max_retries=0)

    logged = next(m for m in caplog.messages if "last raw reply" in m)
    assert "I'm sorry, I cannot comply" in logged
    assert len(logged) < len(junk)  # truncated, not the whole reply


def test_raw_reply_is_capped_at_the_documented_length(make_client, caplog):
    client, _ = make_client(["x" * 5_000])
    with caplog.at_level(logging.ERROR, logger="interview_coach.llm"), pytest.raises(StructuredOutputError):
        client.chat_json([{"role": "user", "content": "go"}], Foo, max_retries=0)

    logged = next(m for m in caplog.messages if "last raw reply" in m)
    assert logged.count("x") == RAW_OUTPUT_LOG_CHARS


# --- R-09: typed failover + per-provider circuit breaker ----------------------------------------


def _auth_error() -> Exception:
    """A revoked/dead API key: the provider answers 401 identically forever."""
    return openai_sdk.AuthenticationError(
        "invalid api key", response=httpx.Response(401, request=_http_request()), body=None
    )


@pytest.mark.parametrize(
    "exc",
    [
        TypeError("chat() got an unexpected keyword argument"),
        ValueError("bad argument"),
        LLMConfigurationError("mimo is not configured"),
        StructuredOutputError("model never produced valid output"),
    ],
    ids=["type-error", "value-error", "misconfiguration", "structured-output"],
)
def test_router_propagates_non_provider_errors_without_failover(exc):
    # The R-09 core: these are OUR failures, not the provider's. Failing over would spend a second
    # provider's tokens on the same broken call and return a plausible answer, hiding the defect.
    primary = _FailingClient(exc)
    fallback = _StaticClient('{"x": 3, "label": "fallback"}')
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    with pytest.raises(type(exc)):
        router.chat([{"role": "user", "content": "go"}])

    assert primary.calls == 1
    assert fallback.calls == 0  # never consulted


def test_router_fails_over_on_empty_completion():
    # A provider that answers with nothing IS failing, so it stays failover-worthy — but it is now
    # a typed EmptyCompletionError rather than a bare ValueError the router cannot tell apart.
    primary = _FailingClient(EmptyCompletionError("mimo returned empty content"))
    fallback = _StaticClient("recovered")
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    assert router.chat([{"role": "user", "content": "go"}]) == "recovered"
    assert fallback.calls == 1


def test_three_auth_failures_open_the_breaker_and_stop_hitting_the_primary():
    # The cost bug this issue is about: a dead key used to pay a wasted primary round-trip on EVERY
    # call, forever. After the threshold the router goes straight to the fallback.
    primary = _FailingClient(_auth_error())
    fallback = _StaticClient("fallback-answer")
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        assert router.chat([{"role": "user", "content": "go"}]) == "fallback-answer"
    assert primary.calls == BREAKER_FAILURE_THRESHOLD
    assert router.breaker_is_open("mimo")

    for _ in range(5):
        assert router.chat([{"role": "user", "content": "go"}]) == "fallback-answer"

    assert primary.calls == BREAKER_FAILURE_THRESHOLD  # not re-hit even once
    assert fallback.calls == BREAKER_FAILURE_THRESHOLD + 5


def test_breaker_half_opens_after_cooldown_and_closes_on_a_successful_probe(monkeypatch):
    clock = {"t": 1_000.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    primary = _SwitchableClient(_auth_error())
    fallback = _StaticClient("fallback-answer")
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        router.chat([{"role": "user", "content": "go"}])
    assert router.breaker_is_open("mimo")

    # Still cooling: the primary stays bypassed.
    clock["t"] += BREAKER_COOLDOWN_SECONDS - 1
    router.chat([{"role": "user", "content": "go"}])
    assert primary.calls == BREAKER_FAILURE_THRESHOLD
    assert router.breaker_is_open("mimo")

    # Cooldown elapsed -> half-open. The provider has recovered, so the probe closes the breaker.
    clock["t"] += 2
    assert not router.breaker_is_open("mimo")
    primary.exc = None
    assert router.chat([{"role": "user", "content": "go"}]) == "primary-answer"
    assert primary.calls == BREAKER_FAILURE_THRESHOLD + 1
    assert not router.breaker_is_open("mimo")

    # Fully closed: traffic is back on the primary and the fallback is idle again.
    assert router.chat([{"role": "user", "content": "go"}]) == "primary-answer"
    assert fallback.calls == BREAKER_FAILURE_THRESHOLD + 1


def test_failed_half_open_probe_re_opens_the_breaker_for_another_cooldown(monkeypatch):
    # Otherwise a still-dead provider would be probed by every call once the first cooldown expired.
    clock = {"t": 500.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    primary = _SwitchableClient(_auth_error())
    router = LLMRouter("mimo", {"mimo": primary, "groq": _StaticClient("fallback-answer")})
    for _ in range(BREAKER_FAILURE_THRESHOLD):
        router.chat([{"role": "user", "content": "go"}])

    clock["t"] += BREAKER_COOLDOWN_SECONDS + 1
    router.chat([{"role": "user", "content": "go"}])  # probe, still dead
    probed = primary.calls
    assert probed == BREAKER_FAILURE_THRESHOLD + 1
    assert router.breaker_is_open("mimo")

    clock["t"] += BREAKER_COOLDOWN_SECONDS - 1  # inside the NEW cooldown
    router.chat([{"role": "user", "content": "go"}])
    assert primary.calls == probed  # one probe per cooldown, not one per call


def test_a_success_resets_the_failure_count_before_the_breaker_trips():
    # Intermittent blips must not accumulate into an open breaker across a healthy provider's life.
    primary = _SwitchableClient(openai_sdk.APIConnectionError(request=_http_request()))
    router = LLMRouter("mimo", {"mimo": primary, "groq": _StaticClient("fallback-answer")})

    for _ in range(BREAKER_FAILURE_THRESHOLD - 1):
        router.chat([{"role": "user", "content": "go"}])
    primary.exc = None
    router.chat([{"role": "user", "content": "go"}])  # success clears the streak
    primary.exc = openai_sdk.APIConnectionError(request=_http_request())
    for _ in range(BREAKER_FAILURE_THRESHOLD - 1):
        router.chat([{"role": "user", "content": "go"}])

    assert not router.breaker_is_open("mimo")


def test_our_own_bugs_never_push_a_provider_toward_the_breaker():
    primary = _FailingClient(TypeError("bad call site"))
    router = LLMRouter("mimo", {"mimo": primary, "groq": _StaticClient("fallback-answer")})

    for _ in range(BREAKER_FAILURE_THRESHOLD + 2):
        with pytest.raises(TypeError):
            router.chat([{"role": "user", "content": "go"}])

    assert not router.breaker_is_open("mimo")


def test_open_breaker_still_probes_the_primary_when_no_fallback_can_serve():
    # With nothing else able to answer there is nothing to save by skipping, and skipping would
    # guarantee the primary is never re-probed by real traffic. Availability wins over fail-fast.
    primary = _SwitchableClient(_auth_error())
    router = LLMRouter("mimo", {"mimo": primary})

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        with pytest.raises(openai_sdk.AuthenticationError):
            router.chat([{"role": "user", "content": "go"}])
    assert router.breaker_is_open("mimo")

    primary.exc = None
    assert router.chat([{"role": "user", "content": "go"}]) == "primary-answer"


def test_breaker_skip_downgrades_a_strict_grammar_the_fallback_cannot_enforce():
    # The bypass path must keep the json_schema downgrade the failover path already had, or a
    # circuit-broken primary turns every structured call into a 400 on the fallback.
    primary = _FailingClient(_auth_error())
    fallback = _StaticClient("{}", supports_json_schema=False)
    router = LLMRouter("mimo", {"mimo": primary, "groq": fallback})
    schema = {"type": "json_schema", "json_schema": {"name": "foo", "schema": {}}}

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        router.chat([{"role": "user", "content": "go"}], response_format=schema)
    router.chat([{"role": "user", "content": "go"}], response_format=schema)

    assert router.breaker_is_open("mimo")
    assert fallback.formats[-1] == {"type": "json_object"}


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
    primary = _ToolClient(error=openai_sdk.APITimeoutError(request=_http_request()))
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


def test_insufficient_quota_fails_fast_without_backoff(monkeypatch, tmp_path, fake_openai_factory):
    # When the DAY's allowance is spent, waiting cannot help — burn zero time and fail loudly.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    fake = fake_openai_factory([_rate_limited(message="You exceeded your current quota: insufficient_quota")])
    client = MimoClient(_provider("mimo"), client=fake)

    with pytest.raises(openai_sdk.RateLimitError):
        client.chat([{"role": "user", "content": "go"}])

    assert fake.call_count == 1
    assert waits == []
    # ADR 0005's addendum calls insufficient_quota the DETECTION half of budget exhaustion; this
    # latch is what carries it to the session-behaviour half (R-25). Without it the exception is
    # swallowed by question_node's failure-isolation net and the fact is lost, so the Session
    # cascades into zero-evidence `failed` questions and exits 0.
    assert usage.quota_exhausted_today("mimo")
    assert not usage.quota_exhausted_today("openai")  # per provider, never a global kill switch


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

    bad_request = openai_sdk.BadRequestError("bad", response=httpx.Response(400, request=_http_request()), body=None)
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


def test_router_downgrades_grammar_for_schema_less_fallback(monkeypatch, tmp_path, fake_openai_factory):
    from interview_coach.llm import OpenAIClient

    # Primary (openai, grammar-capable) dies; fallback (mimo) cannot enforce the grammar. The
    # failover must downgrade to json_object rather than turn an outage into a 400.
    # The tmp ledger keeps the quota latch this raise writes out of the repo's real one.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
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
    timeout_408 = openai_sdk.APIStatusError("timeout", response=httpx.Response(408, request=_http_request()), body=None)
    fake = fake_openai_factory([timeout_408, '{"x": 4, "label": "recovered"}'])
    client = MimoClient(_provider("mimo"), client=fake)
    assert client.chat_json([{"role": "user", "content": "go"}], Foo).x == 4
    assert fake.call_count == 2
