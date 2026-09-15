from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace

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
    OpenAIClient,
    StructuredOutputError,
    ToolCallingUnsupported,
    build_client,
    build_role_clients,
    call_counts,
)
from interview_coach.usage import ProviderQuotaExhausted, usage_for_day


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

    def chat(self, messages, *, response_format=None) -> str:
        self.calls += 1
        self.formats.append(response_format)
        return self.reply


class _FailingClient(LLMClient):
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def chat(self, messages, *, response_format=None) -> str:
        self.calls += 1
        raise self.exc


class _SwitchableClient(LLMClient):
    """A client whose failure can be turned off mid-test — for probing breaker recovery."""

    def __init__(self, exc: Exception | None) -> None:
        self.exc = exc
        self.calls = 0

    def chat(self, messages, *, response_format=None) -> str:
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


def test_groq_and_openai_support_native_tool_calls(fake_openai_factory):
    groq_client = GroqClient(_provider("groq"), client=fake_openai_factory([]))
    openai_client = OpenAIClient(_provider("openai"), client=fake_openai_factory([]))

    assert groq_client.supports_tool_calls is True
    assert openai_client.supports_tool_calls is True


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


def test_same_prompt_parses_with_groq_and_openai(fake_openai_factory):
    prompt = [{"role": "user", "content": "Return the schema."}]
    reply = '{"x": 42, "label": "same-schema"}'
    groq_client = GroqClient(_provider("groq"), client=fake_openai_factory([reply]))
    openai_client = OpenAIClient(_provider("openai"), client=fake_openai_factory([reply]))

    assert groq_client.chat_json(prompt, Foo) == Foo(x=42, label="same-schema")
    assert openai_client.chat_json(prompt, Foo) == Foo(x=42, label="same-schema")


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
    openai = _StaticClient('{"x": 1, "label": "openai"}')
    groq = _StaticClient('{"x": 2, "label": "groq"}')
    router = LLMRouter("groq", {"openai": openai, "groq": groq})

    out = router.chat_json([{"role": "user", "content": "go"}], Foo)

    assert out == Foo(x=2, label="groq")
    assert groq.calls == 1
    assert openai.calls == 0


def test_router_falls_back_on_primary_error():
    # A real transport failure — since R-09 the failover predicate is typed, and a bare RuntimeError
    # (which this test used to pass) is now correctly treated as OUR bug, not the provider's.
    primary = _FailingClient(openai_sdk.APIConnectionError(request=_http_request()))
    fallback = _StaticClient('{"x": 3, "label": "fallback"}')
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

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
    assert per_provider == (("groq", 2),)


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
    before = {"llm.calls": 1, "llm.calls.openai": 1, "sanitizer.whatever": 5}
    after = {"llm.calls": 4, "llm.calls.openai": 1, "llm.calls.groq": 2, "sanitizer.whatever": 9}

    total, per_provider = call_counts(before, after)

    assert total == 3
    assert per_provider == (("groq", 2),)  # openai did not move, so it is not in this turn's split


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
    assert "provider=groq" in line
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
        LLMConfigurationError("groq is not configured"),
        StructuredOutputError("model never produced valid output"),
    ],
    ids=["type-error", "value-error", "misconfiguration", "structured-output"],
)
def test_router_propagates_non_provider_errors_without_failover(exc):
    # The R-09 core: these are OUR failures, not the provider's. Failing over would spend a second
    # provider's tokens on the same broken call and return a plausible answer, hiding the defect.
    primary = _FailingClient(exc)
    fallback = _StaticClient('{"x": 3, "label": "fallback"}')
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

    with pytest.raises(type(exc)):
        router.chat([{"role": "user", "content": "go"}])

    assert primary.calls == 1
    assert fallback.calls == 0  # never consulted


def test_router_fails_over_on_empty_completion():
    # A provider that answers with nothing IS failing, so it stays failover-worthy — but it is now
    # a typed EmptyCompletionError rather than a bare ValueError the router cannot tell apart.
    primary = _FailingClient(EmptyCompletionError("groq returned empty content"))
    fallback = _StaticClient("recovered")
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

    assert router.chat([{"role": "user", "content": "go"}]) == "recovered"
    assert fallback.calls == 1


def test_three_auth_failures_open_the_breaker_and_stop_hitting_the_primary():
    # The cost bug this issue is about: a dead key used to pay a wasted primary round-trip on EVERY
    # call, forever. After the threshold the router goes straight to the fallback.
    primary = _FailingClient(_auth_error())
    fallback = _StaticClient("fallback-answer")
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        assert router.chat([{"role": "user", "content": "go"}]) == "fallback-answer"
    assert primary.calls == BREAKER_FAILURE_THRESHOLD
    assert router.breaker_is_open("groq")

    for _ in range(5):
        assert router.chat([{"role": "user", "content": "go"}]) == "fallback-answer"

    assert primary.calls == BREAKER_FAILURE_THRESHOLD  # not re-hit even once
    assert fallback.calls == BREAKER_FAILURE_THRESHOLD + 5


def test_breaker_half_opens_after_cooldown_and_closes_on_a_successful_probe(monkeypatch):
    clock = {"t": 1_000.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    primary = _SwitchableClient(_auth_error())
    fallback = _StaticClient("fallback-answer")
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        router.chat([{"role": "user", "content": "go"}])
    assert router.breaker_is_open("groq")

    # Still cooling: the primary stays bypassed.
    clock["t"] += BREAKER_COOLDOWN_SECONDS - 1
    router.chat([{"role": "user", "content": "go"}])
    assert primary.calls == BREAKER_FAILURE_THRESHOLD
    assert router.breaker_is_open("groq")

    # Cooldown elapsed -> half-open. The provider has recovered, so the probe closes the breaker.
    clock["t"] += 2
    assert not router.breaker_is_open("groq")
    primary.exc = None
    assert router.chat([{"role": "user", "content": "go"}]) == "primary-answer"
    assert primary.calls == BREAKER_FAILURE_THRESHOLD + 1
    assert not router.breaker_is_open("groq")

    # Fully closed: traffic is back on the primary and the fallback is idle again.
    assert router.chat([{"role": "user", "content": "go"}]) == "primary-answer"
    assert fallback.calls == BREAKER_FAILURE_THRESHOLD + 1


def test_failed_half_open_probe_re_opens_the_breaker_for_another_cooldown(monkeypatch):
    # Otherwise a still-dead provider would be probed by every call once the first cooldown expired.
    clock = {"t": 500.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    primary = _SwitchableClient(_auth_error())
    router = LLMRouter("groq", {"groq": primary, "openai": _StaticClient("fallback-answer")})
    for _ in range(BREAKER_FAILURE_THRESHOLD):
        router.chat([{"role": "user", "content": "go"}])

    clock["t"] += BREAKER_COOLDOWN_SECONDS + 1
    router.chat([{"role": "user", "content": "go"}])  # probe, still dead
    probed = primary.calls
    assert probed == BREAKER_FAILURE_THRESHOLD + 1
    assert router.breaker_is_open("groq")

    clock["t"] += BREAKER_COOLDOWN_SECONDS - 1  # inside the NEW cooldown
    router.chat([{"role": "user", "content": "go"}])
    assert primary.calls == probed  # one probe per cooldown, not one per call


def test_a_success_resets_the_failure_count_before_the_breaker_trips():
    # Intermittent blips must not accumulate into an open breaker across a healthy provider's life.
    primary = _SwitchableClient(openai_sdk.APIConnectionError(request=_http_request()))
    router = LLMRouter("groq", {"groq": primary, "openai": _StaticClient("fallback-answer")})

    for _ in range(BREAKER_FAILURE_THRESHOLD - 1):
        router.chat([{"role": "user", "content": "go"}])
    primary.exc = None
    router.chat([{"role": "user", "content": "go"}])  # success clears the streak
    primary.exc = openai_sdk.APIConnectionError(request=_http_request())
    for _ in range(BREAKER_FAILURE_THRESHOLD - 1):
        router.chat([{"role": "user", "content": "go"}])

    assert not router.breaker_is_open("groq")


def test_our_own_bugs_never_push_a_provider_toward_the_breaker():
    primary = _FailingClient(TypeError("bad call site"))
    router = LLMRouter("groq", {"groq": primary, "openai": _StaticClient("fallback-answer")})

    for _ in range(BREAKER_FAILURE_THRESHOLD + 2):
        with pytest.raises(TypeError):
            router.chat([{"role": "user", "content": "go"}])

    assert not router.breaker_is_open("groq")


def test_open_breaker_still_probes_the_primary_when_no_fallback_can_serve():
    # With nothing else able to answer there is nothing to save by skipping, and skipping would
    # guarantee the primary is never re-probed by real traffic. Availability wins over fail-fast.
    primary = _SwitchableClient(_auth_error())
    router = LLMRouter("groq", {"groq": primary})

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        with pytest.raises(openai_sdk.AuthenticationError):
            router.chat([{"role": "user", "content": "go"}])
    assert router.breaker_is_open("groq")

    primary.exc = None
    assert router.chat([{"role": "user", "content": "go"}]) == "primary-answer"


def test_breaker_skip_downgrades_a_strict_grammar_the_fallback_cannot_enforce():
    # The bypass path must keep the json_schema downgrade the failover path already had, or a
    # circuit-broken primary turns every structured call into a 400 on the fallback.
    primary = _FailingClient(_auth_error())
    fallback = _StaticClient("{}", supports_json_schema=False)
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})
    schema = {"type": "json_schema", "json_schema": {"name": "foo", "schema": {}}}

    for _ in range(BREAKER_FAILURE_THRESHOLD):
        router.chat([{"role": "user", "content": "go"}], response_format=schema)
    router.chat([{"role": "user", "content": "go"}], response_format=schema)

    assert router.breaker_is_open("groq")
    assert fallback.formats[-1] == {"type": "json_object"}


def _dead_router() -> tuple[LLMRouter, _FailingClient]:
    primary = _FailingClient(_auth_error())
    return LLMRouter("groq", {"groq": primary, "openai": _StaticClient("fallback-answer")}), primary


def test_the_breaker_protects_the_next_sessions_router_too():
    # NEW-08: a router is built per Session, so per-instance breaker state protected exactly one
    # Session — the next one re-discovered the same dead provider at full retry cost
    # (BREAKER_FAILURE_THRESHOLD x _TRANSPORT_ATTEMPTS HTTP attempts), forever, which is the opposite
    # of what this module's docstring promises.
    router_a, primary_a = _dead_router()
    for _ in range(BREAKER_FAILURE_THRESHOLD):
        assert router_a.chat([{"role": "user", "content": "go"}]) == "fallback-answer"
    assert primary_a.calls == BREAKER_FAILURE_THRESHOLD
    assert router_a.breaker_is_open("groq")

    router_b, primary_b = _dead_router()

    assert router_b.breaker_is_open("groq")
    assert router_b.chat([{"role": "user", "content": "go"}]) == "fallback-answer"
    assert primary_b.calls == 0  # Session B pays nothing to re-learn the outage


def test_a_concurrent_sessions_router_sees_the_breaker_its_sibling_opened():
    # One daemon thread per Session (web_api), each holding its own router object.
    opened = threading.Barrier(2)
    observed: dict[str, int] = {}
    router_b, primary_b = _dead_router()

    def session_a() -> None:
        router_a, _ = _dead_router()
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            router_a.chat([{"role": "user", "content": "go"}])
        opened.wait(timeout=5)

    def session_b() -> None:
        opened.wait(timeout=5)
        router_b.chat([{"role": "user", "content": "go"}])
        observed["primary_calls"] = primary_b.calls

    threads = [threading.Thread(target=session_a), threading.Thread(target=session_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert observed == {"primary_calls": 0}


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

    def chat(self, messages, *, response_format=None) -> str:
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
    fallback = _ToolClient(result="fallback")
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

    with pytest.raises(ToolCallingUnsupported):
        router.chat_with_tools([{"role": "user", "content": "go"}], **_tool_kwargs())

    assert primary.tool_calls == 1
    assert fallback.tool_calls == 0  # NOT silently retried on the fallback


def test_router_tool_transport_error_fails_over():
    # A transport-level failure (timeout/5xx) is a real outage, so failover to a tool-capable
    # fallback is correct.
    primary = _ToolClient(error=openai_sdk.APITimeoutError(request=_http_request()))
    fallback = _ToolClient(result="fallback-result")
    router = LLMRouter("groq", {"groq": primary, "openai": fallback})

    out = router.chat_with_tools([{"role": "user", "content": "go"}], **_tool_kwargs())

    assert out == "fallback-result"
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
    client = GroqClient(_provider("groq"), client=fake)

    out = client.chat_json([{"role": "user", "content": "go"}], Foo)

    assert out.x == 1
    assert fake.call_count == 3
    assert waits == [2.0, 5.0]  # the fixed schedule when the provider sends no Retry-After
    assert telemetry.snapshot()["transport.backoff.groq"] == 2


def test_transport_backoff_honors_retry_after_header(monkeypatch, fake_openai_factory):
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    fake = fake_openai_factory([_rate_limited(headers={"retry-after": "1"}), '{"x": 1, "label": "ok"}'])
    client = GroqClient(_provider("groq"), client=fake)

    client.chat_json([{"role": "user", "content": "go"}], Foo)

    assert waits == [1.0]


def test_insufficient_quota_fails_fast_without_backoff(monkeypatch, tmp_path, fake_openai_factory):
    # When the DAY's allowance is spent, waiting cannot help — burn zero time and fail loudly.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    fake = fake_openai_factory([_rate_limited(message="You exceeded your current quota: insufficient_quota")])
    client = GroqClient(_provider("groq"), client=fake)

    # GH #119: a TYPED stop, not the SDK's RateLimitError — question_node re-raises it past its
    # failure-isolation net, so a dead quota suspends instead of recording a zero-evidence `failed`.
    with pytest.raises(ProviderQuotaExhausted, match="insufficient_quota"):
        client.chat([{"role": "user", "content": "go"}])

    assert fake.call_count == 1
    assert waits == []
    # ADR 0005's addendum calls insufficient_quota the DETECTION half of budget exhaustion; the latch
    # carries it to the session-behaviour half (R-25) across processes.
    assert usage.quota_exhausted_today("groq")
    assert not usage.quota_exhausted_today("openai")  # per provider, never a global kill switch
    assert llm_module.is_provider_failure(ProviderQuotaExhausted("x"))  # routed roles still fail over


def test_transport_backoff_gives_up_after_bounded_attempts(monkeypatch, fake_openai_factory):
    monkeypatch.setattr(llm_module, "_sleep", lambda _wait: None)
    fake = fake_openai_factory([_rate_limited()])  # the fake repeats its last scripted reply
    client = GroqClient(_provider("groq"), client=fake)

    with pytest.raises(openai_sdk.RateLimitError):
        client.chat([{"role": "user", "content": "go"}])

    assert fake.call_count == llm_module._TRANSPORT_ATTEMPTS


def test_5xx_is_retried_but_4xx_is_not(monkeypatch, fake_openai_factory):
    monkeypatch.setattr(llm_module, "_sleep", lambda _wait: None)
    server_err = openai_sdk.InternalServerError(
        "boom", response=httpx.Response(500, request=_http_request()), body=None
    )
    fake = fake_openai_factory([server_err, '{"x": 2, "label": "recovered"}'])
    client = GroqClient(_provider("groq"), client=fake)
    assert client.chat_json([{"role": "user", "content": "go"}], Foo).x == 2
    assert fake.call_count == 2

    bad_request = openai_sdk.BadRequestError("bad", response=httpx.Response(400, request=_http_request()), body=None)
    fake2 = fake_openai_factory([bad_request])
    client2 = GroqClient(_provider("groq"), client=fake2)
    with pytest.raises(openai_sdk.BadRequestError):
        client2.chat([{"role": "user", "content": "go"}])
    assert fake2.call_count == 1


def test_usage_recorded_to_daily_ledger(monkeypatch, tmp_path, fake_openai_factory):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    fake = fake_openai_factory(
        [{"content": '{"x": 1, "label": "ok"}', "usage": {"prompt_tokens": 100, "completion_tokens": 20}}]
    )
    client = GroqClient(_provider("groq"), client=fake)

    client.chat_json([{"role": "user", "content": "go"}], Foo)

    totals = usage_for_day()
    assert totals["groq"] == {"prompt": 100, "completion": 20, "total": 120, "calls": 1}


# --- M0a / F1: the accounting gate at the provider call boundary ---------------------------------


def _unappendable_ledger(monkeypatch, tmp_path):
    """A ledger path that cannot be appended to, in a directory that can still hold its sidecar."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.mkdir()
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    return ledger


def _break(ledger):
    """Make an already-healthy ledger unappendable, the way a live deployment loses one."""
    ledger.unlink(missing_ok=True)
    ledger.mkdir()


def test_the_call_after_an_unrecordable_one_is_refused(monkeypatch, tmp_path, fake_openai_factory):
    """AC 4: a billed call whose usage row would not write stops the NEXT call from happening.

    The three-call shape is the only honest one for the POST-call fault. A path that is already
    broken is refused before anything is spent (the test below), so the interesting case is the one
    a running deployment actually hits: the ledger was fine, we asked, we were billed, and only then
    did the write fail. The second call cannot be un-billed — what this pins is that there is no
    third one, because a system that keeps spending after it has lost count is spending an amount
    nobody can state. The old `logger.warning(...); return` made exactly that third call.
    """
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    reply = {"content": '{"x": 1, "label": "ok"}', "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    fake = fake_openai_factory([reply, reply, reply])
    client = GroqClient(_provider("groq"), client=fake)

    client.chat_json([{"role": "user", "content": "one"}], Foo)
    assert usage_for_day()["groq"]["calls"] == 1

    _break(ledger)
    client.chat_json([{"role": "user", "content": "two"}], Foo)  # billed; its row cannot be written
    assert fake.call_count == 2

    with pytest.raises(usage.AccountingUnavailable) as caught:
        client.chat_json([{"role": "user", "content": "three"}], Foo)

    assert fake.call_count == 2  # the provider was never asked a third time
    assert "UNRECONCILED" in str(caught.value)
    assert "~120 token(s)" in str(caught.value)  # the spend it cannot account for, stated


def test_an_unwritable_ledger_refuses_the_very_first_call(monkeypatch, tmp_path, fake_openai_factory):
    """AC 3: nothing is billed at all — the gate runs before the request, not after the response.

    Load-bearing for every caller that does NOT pass through `start_refusal_reason`: the bench, the
    forge, and any one-off command. Without the probe here their first call would be spent before
    the missing row had anything to latch.
    """
    _unappendable_ledger(monkeypatch, tmp_path)
    fake = fake_openai_factory(['{"x": 1, "label": "ok"}'])
    client = GroqClient(_provider("groq"), client=fake)

    with pytest.raises(usage.AccountingUnavailable) as caught:
        client.chat_json([{"role": "user", "content": "go"}], Foo)

    assert fake.call_count == 0
    assert "Nothing is unaccounted for yet" in str(caught.value)


def test_a_refused_call_is_not_a_provider_failure(monkeypatch, tmp_path, fake_openai_factory):
    """Our bookkeeping is broken, not the provider's service — so no failover, no breaker trip.

    Failing over here would be the worst possible reading of the fault: it would spend a SECOND
    provider's allowance, equally unrecorded, to work around our own inability to count.
    """
    _unappendable_ledger(monkeypatch, tmp_path)
    primary = GroqClient(_provider("groq"), client=fake_openai_factory(['{"x": 1, "label": "a"}']))
    fallback_fake = fake_openai_factory(['{"x": 2, "label": "b"}'])
    fallback = OpenAIClient(_provider("openai"), client=fallback_fake)
    router = LLMRouter("groq", {"groq": primary, "openai": fallback}, fallback_provider="openai")

    with pytest.raises(usage.AccountingUnavailable):
        router.chat_json([{"role": "user", "content": "go"}], Foo)

    assert fallback_fake.call_count == 0
    assert not llm_module.is_provider_failure(usage.AccountingUnavailable("x"))


def test_the_gate_is_not_swallowed_by_the_structured_output_retry(monkeypatch, tmp_path, fake_openai_factory):
    """`chat_json` retries `(ValidationError, ValueError)`; a gate the caller retries is not a gate.

    Pinned because the obvious exception base for "cannot do this" is ValueError, and choosing it
    would have turned one refusal into three silent re-attempts at the same closed door.
    """
    _unappendable_ledger(monkeypatch, tmp_path)
    fake = fake_openai_factory(['{"x": 1, "label": "ok"}'])
    client = GroqClient(_provider("groq"), client=fake)

    with pytest.raises(usage.AccountingUnavailable):
        client.chat_json([{"role": "user", "content": "go"}], Foo, max_retries=3)

    assert fake.call_count == 0


def test_a_reconciled_ledger_lets_calls_through_again(monkeypatch, tmp_path, fake_openai_factory):
    """The gate has to open again, or "refuse metered work" is just an outage with better wording."""
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    reply = {"content": '{"x": 1, "label": "ok"}', "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    fake = fake_openai_factory([reply, reply, reply])
    client = GroqClient(_provider("groq"), client=fake)

    _break(ledger)
    usage.reset_accounting_state()  # a process that starts with the path already broken
    with pytest.raises(usage.AccountingUnavailable):
        client.chat_json([{"role": "user", "content": "refused"}], Foo)

    ledger.rmdir()
    usage.reconcile_accounting()

    client.chat_json([{"role": "user", "content": "allowed"}], Foo)
    assert fake.call_count == 1
    assert usage_for_day()["groq"] == {"prompt": 100, "completion": 20, "total": 120, "calls": 1}


def _billed_client(replies: list) -> tuple[GroqClient, list]:
    """A client whose transport really is ``openai.OpenAI`` — i.e. one whose calls cost money.

    The suite's usual double is not one, and must not be: a fake that latched an accounting fault
    would refuse the next call in every test that scripts a reply without a ``usage`` block.
    Constructing the SDK object makes no network call; swapping its `create` is what keeps this
    offline.
    """
    sdk = openai_sdk.OpenAI(api_key="test", base_url="http://groq.test", max_retries=0)
    calls: list = []

    def create(**kwargs):
        calls.append(kwargs)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    sdk.chat.completions.create = create
    return GroqClient(_provider("groq"), client=sdk), calls


def _answer(used: object | None) -> SimpleNamespace:
    message = SimpleNamespace(content='{"x": 1, "label": "ok"}', tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=used)


def test_a_billed_call_with_no_token_count_is_held_not_forgiven():
    """A response that states no usage is unknown spend, and unknown is not zero (M0a / NEW-07).

    The call is already paid for; the only question left is whether the system can still say what the
    day cost. Returning quietly here answered "yes, nothing" — the same permissive reading of a
    missing number that the unwritable-ledger case exists to forbid — so the next call goes out
    against a total that is known to be wrong. It latches instead, and that latch stops call two.
    """
    client, calls = _billed_client([_answer(None), _answer(None)])

    client.chat_json([{"role": "user", "content": "one"}], Foo)

    assert len(calls) == 1
    assert usage_for_day().get("groq") is None  # nothing could be counted...
    with pytest.raises(usage.AccountingUnavailable) as caught:
        client.chat_json([{"role": "user", "content": "two"}], Foo)
    assert len(calls) == 1  # ...so there is no second billed call
    assert "UNRECONCILED" in str(caught.value)


def test_a_gateway_that_names_tokens_input_output_is_counted_not_zeroed():
    """`input_tokens`/`output_tokens` is the same number under the other common spelling.

    Read it and the call is accounted for; miss it and the ledger gains a row asserting a real call
    cost nothing, which is worse than no row at all — it is a lie the budget rails average into the
    day.
    """
    client, _ = _billed_client([_answer(SimpleNamespace(input_tokens=90, output_tokens=12))])

    client.chat_json([{"role": "user", "content": "go"}], Foo)

    assert usage_for_day()["groq"] == {"prompt": 90, "completion": 12, "total": 102, "calls": 1}
    assert usage.accounting_fault() is None


def test_a_scripted_test_double_is_not_a_billed_call(fake_openai_factory):
    """The guard rail on the rail: fakes answer without a `usage` block and nobody was charged.

    Latching for them would refuse the second provider call in every test in this suite, so the
    distinction cannot be "the response carried no usage" — it has to be "the transport was real".
    """
    client = GroqClient(_provider("groq"), client=fake_openai_factory(['{"x": 1, "label": "ok"}']))

    client.chat_json([{"role": "user", "content": "one"}], Foo)
    client.chat_json([{"role": "user", "content": "two"}], Foo)

    assert usage.accounting_fault() is None
    assert usage_for_day().get("groq") is None


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
    client = GroqClient(_provider("groq"), client=fake)  # Groq: not verified, opted out

    client.chat_json([{"role": "user", "content": "go"}], Foo, json_schema=TINY_SCHEMA)

    assert fake.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_router_downgrades_grammar_for_schema_less_fallback(monkeypatch, tmp_path, fake_openai_factory):
    # Primary (openai, grammar-capable) dies; fallback (groq) cannot enforce the grammar. The
    # failover must downgrade to json_object rather than turn an outage into a 400.
    # The tmp ledger keeps the quota latch this raise writes out of the repo's real one.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    fake_primary = fake_openai_factory([_rate_limited(message="quota: insufficient_quota")])
    fake_fallback = fake_openai_factory(['{"x": 9, "label": "fallback"}'])
    router = LLMRouter(
        "openai",
        {
            "openai": OpenAIClient(_provider("openai"), client=fake_primary),
            "groq": GroqClient(_provider("groq"), client=fake_fallback),
        },
        fallback_provider="groq",
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
    client = GroqClient(_provider("groq"), client=fake)
    assert client.chat_json([{"role": "user", "content": "go"}], Foo).x == 4
    assert fake.call_count == 2


def test_provider_label_prefers_the_router_identity_over_a_wrapped_client():
    # `provider_label` is the exemption predicate for every R-25 budget rail, so which name wins
    # decides whose allowance the Session is charged against. A router WRAPS concrete clients: its
    # `primary_provider` is the account that pays, and the wrapped client's `provider_name` is not.
    # No shipped class carries both today; the precedence is pinned so that the day one does, the
    # rails do not silently start metering the wrong provider.
    from types import SimpleNamespace

    from interview_coach.llm import UNKNOWN_PROVIDER, provider_label

    assert provider_label(SimpleNamespace(primary_provider="openai", provider_name="groq")) == "openai"
    assert provider_label(SimpleNamespace(provider_name="groq")) == "groq"
    assert provider_label(SimpleNamespace(primary_provider="openai")) == "openai"
    # The demo client and every test fake land here — nothing without a provider spends an allowance.
    assert provider_label(SimpleNamespace()) == UNKNOWN_PROVIDER


# --- the ADR 0009 judge gate lives on the client, not only on the settings path (M0-13 / NEW-24) ---


def _judge_settings(**overrides) -> Settings:
    fields: dict[str, object] = {
        "_env_file": None,
        "primary_provider": "openai",
        "openai_api_key": "test",
        "openai_model": "gpt-5.4-mini",
        "groq_api_key": "test",
        "groq_model": "groq-model",
    }
    fields.update(overrides)
    return Settings(**fields)


def test_a_caller_supplied_provider_client_cannot_become_the_judge():
    # NEW-24: build_role_clients short-circuited to RoleClients.single() for any non-router default,
    # which dropped the bench gate AND the judge pin together, silently. The guard has to live on the
    # client about to BE the judge, or the next caller — a script, a replay tool, a web mode that
    # builds one client to avoid failover — routes around it exactly like this one does.
    settings = _judge_settings()
    groq = GroqClient(settings.provider_config("groq"))

    with pytest.raises(ValueError, match="no green `coach bench` artifact"):
        build_role_clients(settings, groq)


def test_a_fake_or_demo_client_is_still_exempt():
    # The exemption is "not a provider at all", not "not a router": demo mode and every fake-based
    # test must stay on single-client semantics. A fake never calls a provider, spends nobody's
    # allowance, and produces no score anyone compares to a bench artifact.
    fake = _StaticClient('{"x": 1, "label": "fake"}')

    assert build_role_clients(_judge_settings(), fake).judge is fake


def test_an_opted_in_unvalidated_judge_is_logged_loudly_and_stamped(caplog):
    # NEW-25: ADR 0009 grants no exemption, so the hatch stays — it is how `coach bench` measures a
    # candidate model in the first place — but stops being silent. A WARNING at startup, and a mark
    # that survives into the trace and the export so a reader of a score can tell it is not
    # bench-comparable.
    settings = _judge_settings(openai_model="gpt-4o-mini", allow_unvalidated_judge=True)

    with caplog.at_level(logging.WARNING):
        roles = build_role_clients(settings)

    assert roles.judge.judge_unvalidated is True
    assert "unvalidated judge" in caplog.text.lower()
    assert "gpt-4o-mini" in caplog.text


def test_an_unvalidated_judge_is_stamped_into_every_turn_trace_and_the_export():
    from interview_coach.exporter import render_session_markdown
    from interview_coach.microloop import ScriptedCandidate, run_micro_loop
    from interview_coach.rubric import Rubric
    from interview_coach.seeds import SeedQuestion
    from interview_coach.session_serde import TranscriptItem

    judge = _StaticClient(
        json.dumps(
            {
                "dimensions": {
                    "correctness": {"score": 4, "evidence": "cites the tradeoff directly"},
                    # `rubric_with_delivery` adds this dimension for an English Session, and the
                    # judge schema requires a score for every active dimension.
                    "english_delivery": {"score": 4, "evidence": "clear, idiomatic phrasing"},
                },
                "weighted_score": 4.0,
                "confidence": 0.8,
                "follow_up_recommended": False,
                "follow_up_rationale": "n/a",
            }
        )
    )
    judge.judge_unvalidated = True
    seed = SeedQuestion(
        skill="ml_fundamentals",
        question="Explain the bias-variance tradeoff.",
        rubric=Rubric(weights={"correctness": 1.0}),
        answers=("Variance dominates when the model is too flexible.",),
    )

    result = run_micro_loop(judge, seed, ScriptedCandidate(seed.answers), max_turns=1)

    assert result.turns[0].trace.judge_unvalidated is True
    state = {"transcript": [TranscriptItem.from_micro_loop(result, plan_index=0)]}
    assert "UNVALIDATED JUDGE" in render_session_markdown(state)
