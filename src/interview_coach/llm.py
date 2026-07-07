"""Provider-routed LLM access with validated structured output.

Agents depend on :class:`LLMClient` only. Provider details live here: MiMo and Groq are
OpenAI-compatible clients behind an :class:`LLMRouter` that selects ``PRIMARY_PROVIDER`` and falls
back to the other configured provider on primary call failure.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import ProviderName, ProviderSettings, Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# A message can now carry richer fields than plain strings — assistant turns hold a ``tool_calls``
# list and tool turns hold a ``tool_call_id`` — so the value type is widened to ``Any``. Plain
# ``{"role": ..., "content": ...}`` messages remain valid (str is Any), so the other single-shot
# agents are unaffected.
Message = dict[str, Any]
ResponseFormat = dict[str, str]
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

    def chat_json(
        self,
        messages: Sequence[Message],
        response_model: type[T],
        *,
        validators: Sequence[Validator] = (),
        max_retries: int = 1,
        disable_thinking: bool = False,
    ) -> T:
        """Get a schema-valid ``response_model`` from the model.

        Parses the reply, validates it against the pydantic schema, then runs any extra
        ``validators``. On any schema/domain validation failure it feeds the error back and retries
        up to ``max_retries`` times before raising :class:`StructuredOutputError`.
        """
        convo = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            raw = ""
            try:
                raw = self.chat(
                    convo,
                    response_format={"type": "json_object"},
                    disable_thinking=disable_thinking,
                )
                parsed = response_model.model_validate_json(_extract_json(raw))
                for validate in validators:
                    validate(parsed)
                return parsed
            except (ValidationError, ValueError) as err:
                last_error = err
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
        raise ToolCallingUnsupported(
            f"{type(self).__name__} does not support native tool-calling"
        )


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

    def __init__(self, settings: ProviderSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _openai(self) -> Any:
        if not self._settings.configured:
            raise LLMConfigurationError(f"{self.provider_name} is not configured; set its API key, base URL, and model")
        if self._client is None:
            self._client = OpenAI(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                timeout=self._settings.timeout_seconds,
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
        return self._openai().chat.completions.create(**kwargs).choices[0].message

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
            raise ValueError(f"{self.provider_name} returned empty content")
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
            raise ToolCallingUnsupported(
                f"{self.provider_name} returned no tool_calls for a forced tool request"
            )

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


class LLMRouter(LLMClient):
    """Select the primary provider and fail over to the configured fallback on primary errors."""

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

    @property
    def primary_provider(self) -> ProviderName:
        return self._primary_provider

    @property
    def fallback_provider(self) -> ProviderName:
        return self._fallback_provider

    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        disable_thinking: bool = False,
    ) -> str:
        primary = self._clients[self._primary_provider]
        try:
            return primary.chat(
                messages,
                response_format=response_format,
                disable_thinking=disable_thinking,
            )
        except Exception as err:
            fallback = self._clients.get(self._fallback_provider)
            if fallback is None:
                logger.warning(
                    "primary LLM provider %s failed and fallback provider %s is not configured: %s",
                    self._primary_provider,
                    self._fallback_provider,
                    err,
                )
                raise
            logger.warning(
                "primary LLM provider %s failed; falling back to %s: %s",
                self._primary_provider,
                self._fallback_provider,
                err,
            )
            return fallback.chat(
                messages,
                response_format=response_format,
                disable_thinking=disable_thinking,
            )

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
        primary = self._clients[self._primary_provider]
        try:
            return primary.chat_with_tools(messages, **kwargs)
        except ToolCallingUnsupported:
            raise
        except Exception as err:
            fallback = self._clients.get(self._fallback_provider)
            if fallback is None or not fallback.supports_tool_calls:
                raise
            logger.warning(
                "primary provider %s tool-call failed; falling back to %s: %s",
                self._primary_provider,
                self._fallback_provider,
                err,
            )
            return fallback.chat_with_tools(messages, **kwargs)


def build_client(settings: Settings) -> LLMClient:
    """Return the routed LLM client selected by ``PRIMARY_PROVIDER``."""
    clients: dict[ProviderName, LLMClient] = {}
    mimo = settings.provider_config("mimo")
    if mimo.configured:
        clients["mimo"] = MimoClient(mimo)
    groq = settings.provider_config("groq")
    if groq.configured:
        clients["groq"] = GroqClient(groq)
    openai_cfg = settings.provider_config("openai")
    if openai_cfg.configured:
        clients["openai"] = OpenAIClient(openai_cfg)
    return LLMRouter(
        settings.primary_provider,
        clients,
        fallback_provider=settings.fallback_provider,
    )
