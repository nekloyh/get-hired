"""Provider-routed LLM access with validated structured output.

Agents depend on :class:`LLMClient` only. Provider details live here: the OpenAI-compatible clients
sit behind an :class:`LLMRouter` that selects ``PRIMARY_PROVIDER`` and falls back to the other
configured provider when the primary suffers an *outage*.

Failover is typed (R-09): only :func:`is_provider_failure` errors cross to the fallback, and each
provider carries a circuit breaker so a persistently dead one stops costing a wasted round-trip on
every call. Roles that must never change model — the judge above all (ADR 0009 addendum a) — do not
use this router at all; :func:`build_role_clients` pins them to a single provider.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from . import telemetry
from .config import ProviderName, ProviderSettings, RoleName, Settings
from .usage import record_usage

logger = logging.getLogger(__name__)

# Transport-retry policy (free-tier hardening): 429s and transient 5xx/connection failures get a
# bounded, explicit backoff HERE and nowhere else — the SDK's own hidden retries are disabled in
# ``_openai()`` so retry ownership is single (no multiplicative retry stacking). The exception is
# ``insufficient_quota``: when the daily allowance is spent, waiting cannot help, so it fails fast
# and loud instead of burning the timeout budget.
_TRANSPORT_ATTEMPTS = 4  # 1 call + up to 3 backed-off retries
_BACKOFF_SECONDS = (2.0, 5.0, 10.0)
_MAX_RETRY_AFTER_SECONDS = 30.0  # cap on a provider-suggested Retry-After

_sleep = time.sleep  # module-level so tests can stub the wait out
_now = time.monotonic  # breaker cooldowns; monotonic so a wall-clock jump cannot un-open a breaker


def _quota_exhausted(err: Exception) -> bool:
    """A 429 backoff cannot fix: the provider says the day's token allowance is spent."""
    return "insufficient_quota" in f"{getattr(err, 'code', '')} {err}"


def _retryable_transport_error(err: Exception) -> bool:
    if isinstance(err, openai.RateLimitError):
        return not _quota_exhausted(err)
    if isinstance(err, openai.APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(err, openai.APIStatusError):
        # 408/409 are transient (request timeout / conflict) — the SDK's own default retry policy
        # covered them before max_retries=0 moved retry ownership here, so they stay retryable.
        return err.status_code >= 500 or err.status_code in (408, 409)
    return False


def _retry_wait(err: Exception, attempt: int) -> float:
    """Provider's Retry-After when it sent one (capped), else the fixed backoff schedule."""
    headers = getattr(getattr(err, "response", None), "headers", None)
    raw = headers.get("retry-after") if headers is not None else None
    if raw is not None:
        try:
            return min(max(float(raw), 0.0), _MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass
    return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]


T = TypeVar("T", bound=BaseModel)

# A message can now carry richer fields than plain strings — assistant turns hold a ``tool_calls``
# list and tool turns hold a ``tool_call_id`` — so the value type is widened to ``Any``. Plain
# ``{"role": ..., "content": ...}`` messages remain valid (str is Any), so the other single-shot
# agents are unaffected.
Message = dict[str, Any]
# json_object mode is flat strings; json_schema mode nests the full grammar — hence Any values.
ResponseFormat = dict[str, Any]
Validator = Callable[[Any], None]
ToolSpec = dict[str, Any]
# Executes one tool call: receives the tool name and parsed JSON arguments, returns the result
# string that is fed back to the model as the ``tool`` turn.
ToolExecutor = Callable[[str, dict[str, Any]], str]


class StructuredOutputError(RuntimeError):
    """Raised when the model cannot produce schema-valid output within the retry budget."""


class LLMConfigurationError(RuntimeError):
    """Raised when a requested provider is not configured well enough to call."""


class ToolCallingUnsupported(RuntimeError):
    """Raised when a provider cannot (or is configured not to) do native tool-calling.

    The Interviewer may use this for clients that truly have no tool API, but supported providers
    should surface native tool failures rather than silently degrading.
    """


class EmptyCompletionError(ValueError):
    """The provider answered, but with no usable content.

    Subclasses ``ValueError`` so the pre-R-09 callers that catch ValueError are unaffected, and is
    typed so the router can count it as a *provider* failure — worth failing over, worth counting
    against the breaker — while a ValueError raised by our own code still propagates untouched.
    """


def is_provider_failure(err: BaseException) -> bool:
    """Whether ``err`` is the provider failing, as opposed to us calling it wrong (R-09).

    This is the entire failover predicate. ``openai.APIError`` is the SDK's umbrella over every
    provider-reported failure — connection, timeout, 4xx and 5xx alike — so the APIError /
    APIConnectionError / APITimeoutError trio all match it. Everything else is ours: a ``TypeError``
    from a bad call site, an :class:`LLMConfigurationError` from a half-configured provider, a
    :class:`StructuredOutputError` the model earned. Those used to be indistinguishable from an
    outage, so a code bug would silently spend a second provider's tokens and return *something* —
    hiding the defect behind a plausible answer. They now propagate.
    """
    return isinstance(err, (openai.APIError, EmptyCompletionError))


# Per-provider circuit breaker (R-09). A provider that failed this many times in a row is not going
# to serve the next call either — a revoked API key returns 401 identically forever — so the router
# stops paying its round-trip and goes straight to the fallback. Without this, a dead key costs two
# round-trips on EVERY call for as long as it stays dead.
#
# Retry ownership stays single, unchanged from the free-tier hardening work. The layers are:
#
#   1. SDK retries          disabled (`max_retries=0` in ``_openai()``)
#   2. client ``_create()`` up to ``_TRANSPORT_ATTEMPTS`` with explicit backoff — the ONLY retries
#   3. router failover      a different provider, never a repeat of the same call
#   4. router breaker       stop calling a provider that keeps failing
#
# Nothing here retries; the breaker counts *post-retry* outcomes, so one tripped breaker step means
# layer 2 already exhausted its budget. That is why the threshold reads differently per error class
# and should: a 401 is not retryable, so three failures cost three primary calls (the DoD case),
# while a 429/5xx costs three fully backed-off rounds before the breaker opens — which is correct,
# because a provider still 429-ing after its own Retry-After deserves more patience than a dead key.
BREAKER_FAILURE_THRESHOLD = 3
# After this long the next call is allowed through as a half-open probe: one real request decides
# whether the provider is back. A success closes the breaker; a failure re-opens it for another
# cooldown, so a still-dead provider costs one probe per minute rather than one per call.
BREAKER_COOLDOWN_SECONDS = 60.0


@dataclass
class _Breaker:
    """One provider's consecutive-failure state.

    Deliberately unlocked: the rest of this codebase's shared counters (telemetry, the usage ledger)
    are unsynchronised too, and the worst a torn update can do here is miscount a single failure —
    which delays or advances an open by one call and self-corrects on the next success.
    """

    failures: int = 0
    opened_at: float | None = None


# --- per-call trace (R-26) ----------------------------------------------------------------------

# Greppable prefix for the one-line-per-call trace. One line per PROVIDER CALL — retries and
# failures included — because the thing being diagnosed is precisely the call that misbehaved.
CALL_LOG_PREFIX = "llm-call"

# Counter keys, deliberately layered onto the existing telemetry module rather than a parallel
# accounting system (the issue's "extend, don't duplicate"): the bench and forge already snapshot
# and diff these counters, so per-call accounting comes along for free in those reports.
LLM_CALL_KEY = "llm.calls"
LLM_CALL_PROVIDER_PREFIX = "llm.calls."

# How much of a rejected reply to log when structured output finally fails. Enough to see whether
# the model produced prose, a code fence, a truncated object, or a refusal — which are four very
# different bugs that all surface identically as "could not obtain schema-valid output".
RAW_OUTPUT_LOG_CHARS = 500


def call_counts(before: Mapping[str, int], after: Mapping[str, int]) -> tuple[int, tuple[tuple[str, int], ...]]:
    """Provider calls made between two telemetry snapshots: total, and the per-provider split.

    The per-provider split is what makes a silent failover legible after the fact: a judge phase
    that recorded calls against a provider the role was never pinned to is the ADR 0009 failure
    mode, and without this it leaves no trace at all in the export.
    """
    moved = telemetry.delta(before, after)
    per_provider = tuple(
        sorted(
            (key[len(LLM_CALL_PROVIDER_PREFIX) :], count)
            for key, count in moved.items()
            if key.startswith(LLM_CALL_PROVIDER_PREFIX)
        )
    )
    return moved.get(LLM_CALL_KEY, 0), per_provider


class LLMClient(ABC):
    """The abstract interface every agent depends on."""

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        disable_thinking: bool = False,
    ) -> str:
        """Return raw assistant content for ``messages``."""

    @property
    def supports_json_schema(self) -> bool:
        """Whether this client can enforce strict ``response_format: json_schema`` grammars.

        Constrained decoding kills structural noise at the source — a model literally cannot
        flatten the judgment into ``dimensions`` or score a weight-0 dimension when the grammar
        forbids the keys. Off by default; only clients whose support is live-verified opt in.
        """
        return False

    def chat_json(
        self,
        messages: Sequence[Message],
        response_model: type[T],
        *,
        validators: Sequence[Validator] = (),
        max_retries: int = 1,
        disable_thinking: bool = False,
        json_schema: Mapping[str, Any] | None = None,
    ) -> T:
        """Get a schema-valid ``response_model`` from the model.

        Parses the reply, validates it against the pydantic schema, then runs any extra
        ``validators``. On any schema/domain validation failure it feeds the error back and retries
        up to ``max_retries`` times before raising :class:`StructuredOutputError`.

        ``json_schema`` (a bare JSON Schema dict) upgrades the request to strict constrained
        decoding on clients that support it (probed live on gpt-5.4-mini 2026-07-11); everywhere
        else it is ignored and the parse-and-repair loop stays the only guard. The pydantic +
        validator pipeline still runs either way — the grammar is an upstream filter, not a
        replacement for validation.
        """
        response_format: dict[str, Any] = {"type": "json_object"}
        if json_schema is not None and self.supports_json_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": True,
                    "schema": dict(json_schema),
                },
            }
        convo = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            raw = ""
            try:
                raw = self.chat(
                    convo,
                    response_format=response_format,
                    disable_thinking=disable_thinking,
                )
                parsed = response_model.model_validate_json(_extract_json(raw))
                for validate in validators:
                    validate(parsed)
                return parsed
            except (ValidationError, ValueError) as err:
                last_error = err
                telemetry.incr("structured_output.invalid_reply")
                logger.warning("structured-output attempt %d failed: %s", attempt + 1, err)
                if attempt < max_retries:
                    convo = [
                        *convo,
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                f"Your previous response was invalid:\n{err}\n\n"
                                "Return ONLY a corrected JSON object that satisfies the schema — "
                                "no prose, no code fences."
                            ),
                        },
                    ]
        # Without the raw reply, prose, a code fence, a truncated object, and a refusal are four
        # very different bugs that all surface identically as "could not obtain schema-valid
        # output". Logged rather than folded into the message so the exception text (which callers
        # and the degrade paths match on) stays stable, and so a full reply cannot blow up a
        # user-facing error.
        logger.error(
            "structured output failed after %d attempt(s); last raw reply (first %d chars): %s",
            max_retries + 1,
            RAW_OUTPUT_LOG_CHARS,
            raw[:RAW_OUTPUT_LOG_CHARS] if raw else "<no reply — the call itself failed>",
        )
        raise StructuredOutputError(
            f"could not obtain schema-valid output after {max_retries + 1} attempt(s)"
        ) from last_error

    @property
    def supports_tool_calls(self) -> bool:
        """Whether this client can do native (provider-level) function-calling.

        Defaults to ``False`` so callers must opt in; clients with verified support override it.
        """
        return False

    def chat_with_tools(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSpec],
        tool_executor: ToolExecutor,
        response_model: type[T],
        final_instruction: str,
        validators: Sequence[Validator] = (),
        tool_choice: Any = "auto",
        max_retries: int = 1,
        disable_thinking: bool = True,
    ) -> T:
        """Run one native tool round-trip, then return a schema-valid ``response_model``.

        The model is asked to call a tool; ``tool_executor`` runs it; the result is appended as a
        ``tool`` turn; then ``final_instruction`` asks the model for the final structured answer,
        which is validated exactly like :meth:`chat_json` (with the same retry-on-failure loop).

        Raises :class:`ToolCallingUnsupported` when the provider cannot do native tool-calling, so
        the caller can fall back to a non-tool path.
        """
        raise ToolCallingUnsupported(f"{type(self).__name__} does not support native tool-calling")


def _extract_json(content: str) -> str:
    """Pull a JSON object out of a reply, tolerating ```json fences and surrounding prose."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return text


class _OpenAICompatibleClient(LLMClient):
    """Shared OpenAI-compatible provider plumbing."""

    provider_name: ProviderName
    # Opt-in flag: only clients whose native function-calling is verified set this True.
    _supports_tools: bool = False
    # Class-level default for strict json_schema decoding; per-instance config wins (the provider
    # entry binds one model, so the ProviderSettings override is effectively per-model).
    _default_supports_json_schema: bool = False

    def __init__(self, settings: ProviderSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    @property
    def supports_json_schema(self) -> bool:
        if self._settings.supports_json_schema is not None:
            return self._settings.supports_json_schema
        return self._default_supports_json_schema

    @property
    def model_name(self) -> str:
        """The concrete model this client calls — report labels must name the real judge."""
        return self._settings.model

    def _openai(self) -> Any:
        if not self._settings.configured:
            raise LLMConfigurationError(f"{self.provider_name} is not configured; set its API key, base URL, and model")
        if self._client is None:
            self._client = OpenAI(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                timeout=self._settings.timeout_seconds,
                # Retries are owned by _create()'s explicit backoff; the SDK's hidden default
                # (max_retries=2) would stack multiplicatively under it.
                max_retries=0,
            )
        return self._client

    def _create(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        tools: Sequence[ToolSpec] | None = None,
        tool_choice: Any = None,
        disable_thinking: bool = False,
    ) -> Any:
        """Issue one completion and return the raw assistant message (content and/or tool_calls)."""
        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": list(messages),
            "temperature": self._settings.temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools is not None:
            kwargs["tools"] = list(tools)
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if extra_body := self._thinking_extra_body(disable_thinking):
            kwargs["extra_body"] = extra_body
        for attempt in range(_TRANSPORT_ATTEMPTS):
            started = _now()
            try:
                completion = self._openai().chat.completions.create(**kwargs)
            except Exception as err:
                quota_dead = isinstance(err, openai.RateLimitError) and _quota_exhausted(err)
                will_retry = not quota_dead and attempt + 1 < _TRANSPORT_ATTEMPTS and _retryable_transport_error(err)
                # Traced before the raise, so a call that died still leaves its line — the failing
                # call is the whole point of the trace.
                self._trace_call(started, outcome=f"{'retry' if will_retry else 'error'}:{type(err).__name__}")
                if quota_dead:
                    logger.error(
                        "%s daily quota exhausted (insufficient_quota) — backoff cannot help; "
                        "check today's spend in %s",
                        self.provider_name,
                        "logs/usage-ledger.jsonl",
                    )
                    raise
                if not will_retry:
                    raise
                wait = _retry_wait(err, attempt)
                telemetry.incr(f"transport.backoff.{self.provider_name}")
                logger.warning(
                    "%s transport error (attempt %d/%d): %s — backing off %.1fs",
                    self.provider_name,
                    attempt + 1,
                    _TRANSPORT_ATTEMPTS,
                    err,
                    wait,
                )
                _sleep(wait)
            else:
                self._record_usage(completion)
                self._trace_call(started, outcome="ok", completion=completion)
                return completion.choices[0].message
        raise AssertionError("unreachable: transport retry loop always returns or raises")

    def _trace_call(self, started: float, *, outcome: str, completion: Any = None) -> None:
        """Count this provider call and emit its one-line trace (R-26).

        Instrumented HERE, at the concrete client, rather than in the router: the pinned role
        clients — the judge above all (ADR 0009 addendum a) — never pass through the router, so
        router-level accounting would miss exactly the calls the ADR cares most about.
        """
        used = getattr(completion, "usage", None)
        telemetry.incr(LLM_CALL_KEY)
        telemetry.incr(f"{LLM_CALL_PROVIDER_PREFIX}{self.provider_name}")
        logger.info(
            "%s provider=%s model=%s ms=%.0f prompt=%d completion=%d outcome=%s",
            CALL_LOG_PREFIX,
            self.provider_name,
            self._settings.model,
            (_now() - started) * 1000.0,
            getattr(used, "prompt_tokens", 0) or 0,
            getattr(used, "completion_tokens", 0) or 0,
            outcome,
        )

    def _record_usage(self, completion: Any) -> None:
        """Append this call's token usage to the daily ledger (fakes without ``usage`` are skipped)."""
        used = getattr(completion, "usage", None)
        if used is None:
            return
        record_usage(
            self.provider_name,
            self._settings.model,
            prompt_tokens=getattr(used, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(used, "completion_tokens", 0) or 0,
        )

    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        disable_thinking: bool = False,
    ) -> str:
        message = self._create(messages, response_format=response_format, disable_thinking=disable_thinking)
        content = self._extract_content(message)
        if not content.strip():
            raise EmptyCompletionError(f"{self.provider_name} returned empty content")
        return content

    @property
    def supports_tool_calls(self) -> bool:
        return self._supports_tools

    def chat_with_tools(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSpec],
        tool_executor: ToolExecutor,
        response_model: type[T],
        final_instruction: str,
        validators: Sequence[Validator] = (),
        tool_choice: Any = "auto",
        max_retries: int = 1,
        disable_thinking: bool = True,
    ) -> T:
        if not self._supports_tools:
            raise ToolCallingUnsupported(f"{self.provider_name} has native tool-calling disabled")

        convo: list[Message] = list(messages)
        first = self._create(
            convo,
            tools=tools,
            tool_choice=tool_choice,
            disable_thinking=disable_thinking,
        )
        tool_calls = list(getattr(first, "tool_calls", None) or [])
        if not tool_calls:
            # Forced a tool call but the provider answered with prose — treat as unsupported so the
            # caller can fail loudly or intentionally route to a non-native fake path.
            raise ToolCallingUnsupported(f"{self.provider_name} returned no tool_calls for a forced tool request")

        convo.append(self._assistant_tool_message(first, tool_calls))
        for call in tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as err:
                raise ValueError(f"{self.provider_name} tool arguments were not valid JSON: {err}") from err
            result = tool_executor(name, args)
            convo.append({"role": "tool", "tool_call_id": call.id, "content": result})

        # The final answer reuses the exact structured-output contract (parse + validators + retry).
        convo.append({"role": "user", "content": final_instruction})
        return self.chat_json(
            convo,
            response_model,
            validators=validators,
            max_retries=max_retries,
            disable_thinking=disable_thinking,
        )

    def _assistant_tool_message(self, message: Any, tool_calls: Sequence[Any]) -> Message:
        """Rebuild the assistant turn for replay, carrying only content + tool_calls.

        Crucially this never copies ``reasoning_content`` back into the history (ADR 0003): the
        thinking quirk must not be replayed across a multi-turn tool conversation.
        """
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in tool_calls
            ],
        }

    def _thinking_extra_body(self, disable_thinking: bool) -> dict[str, Any] | None:
        return None

    def _extract_content(self, message: Any) -> str:
        return message.content or ""


class MimoClient(_OpenAICompatibleClient):
    """OpenAI-compatible client for MiMo.

    The thinking-mode ``reasoning_content`` quirk is quarantined here, per ADR 0003: the answer is
    read from ``message.content`` and ``reasoning_content`` is never fed to the JSON parser. Keeping
    that handling inside this client is exactly what issue 0004 requires when the router lands.
    """

    provider_name: ProviderName = "mimo"
    _supports_tools: bool = True

    def _thinking_extra_body(self, disable_thinking: bool) -> dict[str, Any] | None:
        if not disable_thinking:
            return None
        return {"thinking": {"type": "disabled"}}

    def _extract_content(self, message: Any) -> str:
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None and getattr(message, "model_extra", None):
            reasoning = message.model_extra.get("reasoning_content")
        if reasoning:
            logger.debug("MiMo reasoning_content (%d chars) ignored for parsing", len(reasoning))
        return super()._extract_content(message)


class GroqClient(_OpenAICompatibleClient):
    """OpenAI-compatible client for Groq, with native function-calling enabled.

    Groq is the 2026-06-03 cutover target and shares the same OpenAI-compatible tool-call path as
    MiMo. The Interviewer remains the only caller of this API (ADR 0003).
    """

    provider_name: ProviderName = "groq"
    _supports_tools: bool = True


class OpenAIClient(_OpenAICompatibleClient):
    """OpenAI-compatible client for the OpenAI API itself (e.g. gpt-4o-mini).

    The reference OpenAI-compatible implementation — no vendor quirks to quarantine. Native
    function-calling is enabled so it can drive the Interviewer's tool path and the calibration bench.
    """

    provider_name: ProviderName = "openai"
    _supports_tools: bool = True
    # Live-probed on gpt-5.4-mini (2026-07-11): strict grammars accepted, including nested
    # objects, arrays, and minimum/maximum bounds. Groq/MiMo stay opted out until verified;
    # a per-model env override (<PROVIDER>_SUPPORTS_JSON_SCHEMA) can flip any of them.
    _default_supports_json_schema: bool = True


class ZenMuxClient(_OpenAICompatibleClient):
    """OpenAI-compatible client for ZenMux — an **availability** tier, never the judge.

    ZenMux aggregates many upstream models behind one OpenAI-compatible endpoint, which is exactly
    what makes it useful as a fallback and exactly why it must not score: the model actually serving
    a request is the aggregator's decision, so "the judge" would not be a fixed model at all. ADR
    0009's pinning requires a named model with a green bench artifact, and a router-of-routers
    cannot satisfy that by construction. Enforced in `Settings._require_bench_validated_judge`.

    Capabilities are opted out until measured, per ADR 0003's tools-per-proven-need rule: whether
    the served model supports function-calling or strict `json_schema` grammars depends on which
    upstream it lands on. `ZENMUX_SUPPORTS_JSON_SCHEMA=true` flips the grammar path once a specific
    model is pinned and verified.
    """

    provider_name: ProviderName = "zenmux"
    _supports_tools: bool = False


class LLMRouter(LLMClient):
    """Select the primary provider and fail over to the configured fallback on primary *outages*.

    Failover is typed (R-09): only :func:`is_provider_failure` errors cross to the fallback. A bug
    in our own call, a configuration error, or a model that could not produce valid output all
    propagate — masking those behind a second provider's answer is how a defect ships looking fine.

    Each provider additionally carries a circuit breaker, so a persistently dead provider stops
    costing a wasted round-trip on every single call.
    """

    def __init__(
        self,
        primary_provider: ProviderName,
        clients: Mapping[ProviderName, LLMClient],
        *,
        fallback_provider: ProviderName | None = None,
    ) -> None:
        self._primary_provider = primary_provider
        self._fallback_provider: ProviderName = fallback_provider or ("groq" if primary_provider == "mimo" else "mimo")
        self._clients = dict(clients)
        if self._primary_provider not in self._clients:
            raise LLMConfigurationError(f"primary provider {self._primary_provider!r} is not configured")
        self._breakers: dict[ProviderName, _Breaker] = {}

    # --- circuit breaker ------------------------------------------------------------------------

    def breaker_is_open(self, provider: ProviderName) -> bool:
        """Whether ``provider`` is currently tripped and still inside its cooldown.

        Returns False once the cooldown has elapsed — that is the half-open state, and the caller
        letting one real request through is what probes recovery. The probe's own outcome
        (:meth:`_record_success` / :meth:`_record_failure`) then closes or re-opens the breaker, so
        only one probe per cooldown window ever reaches a provider that is still down.
        """
        breaker = self._breakers.get(provider)
        if breaker is None or breaker.opened_at is None:
            return False
        return (_now() - breaker.opened_at) < BREAKER_COOLDOWN_SECONDS

    def _record_success(self, provider: ProviderName) -> None:
        breaker = self._breakers.get(provider)
        if breaker is None or (breaker.failures == 0 and breaker.opened_at is None):
            return
        if breaker.opened_at is not None:
            telemetry.incr(f"router.breaker_close.{provider}")
            logger.info("provider %s answered again; closing its circuit breaker", provider)
        breaker.failures = 0
        breaker.opened_at = None

    def _record_failure(self, provider: ProviderName) -> None:
        breaker = self._breakers.setdefault(provider, _Breaker())
        breaker.failures += 1
        if breaker.failures < BREAKER_FAILURE_THRESHOLD:
            return
        already_open = breaker.opened_at is not None
        # Re-stamped on every failure at or past the threshold, so a failed half-open probe starts a
        # fresh cooldown instead of letting every subsequent call through.
        breaker.opened_at = _now()
        if not already_open:
            telemetry.incr(f"router.breaker_open.{provider}")
            logger.warning(
                "provider %s failed %d consecutive times; opening its circuit breaker for %.0fs "
                "(calls route straight to the fallback until a probe succeeds)",
                provider,
                breaker.failures,
                BREAKER_COOLDOWN_SECONDS,
            )

    def _call(self, provider: ProviderName, call: Callable[[LLMClient], Any]) -> Any:
        """Invoke one provider, recording the outcome against its breaker.

        Only provider failures count. A ``TypeError`` from our own call site must not push a healthy
        provider toward being cut off.
        """
        try:
            result = call(self._clients[provider])
        except Exception as err:
            if is_provider_failure(err):
                self._record_failure(provider)
            raise
        self._record_success(provider)
        return result

    def _usable_fallback(self, *, needs_tools: bool = False) -> LLMClient | None:
        fallback = self._clients.get(self._fallback_provider)
        if fallback is None or (needs_tools and not fallback.supports_tool_calls):
            return None
        return fallback

    def _skip_primary_for(self, fallback: LLMClient | None) -> bool:
        """Whether to bypass a tripped primary — only ever when something else can actually serve.

        With no usable fallback there is nothing to save: the call would fail either way, and
        skipping would additionally guarantee the primary is never re-probed by real traffic. So an
        open breaker degrades to "try anyway" rather than "fail fast" when it stands alone.
        """
        return fallback is not None and self.breaker_is_open(self._primary_provider)

    @staticmethod
    def _downgraded_format(response_format: ResponseFormat | None, fallback: LLMClient) -> ResponseFormat | None:
        """Strip a strict grammar the fallback cannot enforce, so an outage does not become a 400."""
        if (
            response_format is not None
            and response_format.get("type") == "json_schema"
            and not fallback.supports_json_schema
        ):
            # Plain JSON mode instead; parse-and-repair carries the schema burden from here.
            return {"type": "json_object"}
        return response_format

    @property
    def primary_provider(self) -> ProviderName:
        return self._primary_provider

    @property
    def fallback_provider(self) -> ProviderName:
        return self._fallback_provider

    @property
    def supports_json_schema(self) -> bool:
        return self._clients[self._primary_provider].supports_json_schema

    @property
    def model_name(self) -> str:
        return getattr(self._clients[self._primary_provider], "model_name", "")

    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        disable_thinking: bool = False,
    ) -> str:
        fallback = self._usable_fallback()

        def on_fallback(client: LLMClient) -> str:
            return client.chat(
                messages,
                response_format=self._downgraded_format(response_format, client),
                disable_thinking=disable_thinking,
            )

        if self._skip_primary_for(fallback):
            telemetry.incr(f"router.breaker_skip.{self._primary_provider}")
            logger.warning(
                "primary LLM provider %s is circuit-broken; routing straight to %s",
                self._primary_provider,
                self._fallback_provider,
            )
            return self._call(self._fallback_provider, on_fallback)

        try:
            return self._call(
                self._primary_provider,
                lambda client: client.chat(
                    messages,
                    response_format=response_format,
                    disable_thinking=disable_thinking,
                ),
            )
        except Exception as err:
            if not is_provider_failure(err):
                # Our bug, our misconfiguration, or the model's own failure to comply — a second
                # provider would answer the same broken question and bury the defect.
                raise
            if fallback is None:
                logger.warning(
                    "primary LLM provider %s failed and fallback provider %s is not configured: %s",
                    self._primary_provider,
                    self._fallback_provider,
                    err,
                )
                raise
            telemetry.incr(f"router.failover.{self._primary_provider}")
            logger.warning(
                "primary LLM provider %s failed; falling back to %s: %s",
                self._primary_provider,
                self._fallback_provider,
                err,
            )
            return self._call(self._fallback_provider, on_fallback)

    @property
    def supports_tool_calls(self) -> bool:
        return self._clients[self._primary_provider].supports_tool_calls

    def chat_with_tools(self, messages: Sequence[Message], **kwargs: Any) -> Any:
        # A tool conversation cannot be split across providers (tool_call_ids are provider-bound),
        # so failover happens at the whole-loop boundary, and only to a fallback that itself can do
        # native tool-calling.
        #
        # ToolCallingUnsupported is a capability/decline signal, not a transient outage. Failing over
        # on it would silently hide exactly the tool-call integration problem this path exists to
        # surface, so it propagates. Only transport-level errors trigger failover.
        fallback = self._usable_fallback(needs_tools=True)

        def run(client: LLMClient) -> Any:
            return client.chat_with_tools(messages, **kwargs)

        if self._skip_primary_for(fallback):
            telemetry.incr(f"router.breaker_skip.{self._primary_provider}")
            logger.warning(
                "primary provider %s is circuit-broken; routing tool-call straight to %s",
                self._primary_provider,
                self._fallback_provider,
            )
            return self._call(self._fallback_provider, run)

        try:
            return self._call(self._primary_provider, run)
        except ToolCallingUnsupported:
            raise
        except Exception as err:
            if not is_provider_failure(err) or fallback is None:
                raise
            telemetry.incr(f"router.failover.{self._primary_provider}")
            logger.warning(
                "primary provider %s tool-call failed; falling back to %s: %s",
                self._primary_provider,
                self._fallback_provider,
                err,
            )
            return self._call(self._fallback_provider, run)


_CLIENT_CLASSES: dict[ProviderName, type[_OpenAICompatibleClient]] = {
    "mimo": MimoClient,
    "groq": GroqClient,
    "openai": OpenAIClient,
    "zenmux": ZenMuxClient,
}


def build_client(settings: Settings) -> LLMClient:
    """Return the routed LLM client selected by ``PRIMARY_PROVIDER``."""
    clients: dict[ProviderName, LLMClient] = {}
    for provider, client_cls in _CLIENT_CLASSES.items():
        config = settings.provider_config(provider)
        if config.configured:
            clients[provider] = client_cls(config)
    return LLMRouter(
        settings.primary_provider,
        clients,
        fallback_provider=settings.fallback_provider,
    )


@dataclass(frozen=True)
class RoleClients:
    """The per-role client bundle (ADR 0010).

    ``judge`` is always a *pinned* provider client, never the failover router: per ADR 0009's
    gate-as-code addendum, a judge-role failure must surface (retry-same-model happens at the
    transport layer; the per-question net records a visible ``failed``) rather than silently hand
    scoring to a model that never passed the bench. The other roles default to the shared router —
    the exact pre-0010 object — so an unconfigured role behaves byte-identically to before.
    """

    judge: LLMClient
    interviewer: LLMClient
    supervisor: LLMClient
    diagnostic: LLMClient
    planner: LLMClient

    @classmethod
    def single(cls, client: LLMClient) -> RoleClients:
        """Every role served by one client — the semantics of fakes, demo mode, and direct calls."""
        return cls(
            judge=client,
            interviewer=client,
            supervisor=client,
            diagnostic=client,
            planner=client,
        )


def ensure_role_clients(client: RoleClients | LLMClient | None) -> RoleClients | None:
    """Normalize a call-site input: a bundle passes through, a bare client serves every role."""
    if client is None or isinstance(client, RoleClients):
        return client
    return RoleClients.single(client)


def _pinned_role_client(settings: Settings, role: RoleName) -> LLMClient:
    """A single-provider client for ``role`` — no failover wrapper, overrides applied."""
    config = settings.role_config(role)
    if not config.configured:
        raise LLMConfigurationError(
            f"role {role!r} resolves to provider {config.name!r} which is not configured; "
            "set its API key, base URL, and model"
        )
    return _CLIENT_CLASSES[config.name](config)


def build_role_clients(settings: Settings, default_client: LLMClient | None = None) -> RoleClients:
    """Build the ADR 0010 role bundle.

    ``default_client`` is the already-built session client (router, demo, or a test fake). A
    non-router default carries no provider identity to pin or route, so it serves every role
    unchanged — which keeps demo mode and every existing fake-based test on single-client
    semantics. With a real router: the judge is pinned to its resolved provider client (ADR
    0009a), and only roles with ROLE_* env overrides get their own pinned client — everything
    else shares the router object itself.
    """
    default = default_client if default_client is not None else build_client(settings)
    if not isinstance(default, LLMRouter) or not hasattr(settings, "role_config"):
        # No router = nothing to pin or route (fakes, demo mode). No ``role_config`` = a partial
        # settings double (several CLI tests fake Settings with a SimpleNamespace) — role routing
        # only applies to the real Settings contract.
        return RoleClients.single(default)
    non_judge: dict[str, LLMClient] = {}
    for role in ("interviewer", "supervisor", "diagnostic", "planner"):
        non_judge[role] = _pinned_role_client(settings, role) if settings.role_overridden(role) else default
    return RoleClients(judge=_pinned_role_client(settings, "judge"), **non_judge)
