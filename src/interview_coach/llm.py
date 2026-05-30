"""Provider-routed LLM access with validated structured output.

Agents depend on :class:`LLMClient` only. Provider details live here: MiMo and Groq are
OpenAI-compatible clients behind an :class:`LLMRouter` that selects ``PRIMARY_PROVIDER`` and falls
back to the other configured provider on primary call failure.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import ProviderName, ProviderSettings, Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Message = dict[str, str]
ResponseFormat = dict[str, str]
Validator = Callable[[Any], None]


class StructuredOutputError(RuntimeError):
    """Raised when the model cannot produce schema-valid output within the retry budget."""


class LLMConfigurationError(RuntimeError):
    """Raised when a requested provider is not configured well enough to call."""


class LLMClient(ABC):
    """The abstract interface every agent depends on."""

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
    ) -> str:
        """Return raw assistant content for ``messages``."""

    def chat_json(
        self,
        messages: Sequence[Message],
        response_model: type[T],
        *,
        validators: Sequence[Validator] = (),
        max_retries: int = 1,
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
                raw = self.chat(convo, response_format={"type": "json_object"})
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

    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": list(messages),
            "temperature": self._settings.temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        resp = self._openai().chat.completions.create(**kwargs)
        content = self._extract_content(resp.choices[0].message)
        if not content.strip():
            raise ValueError(f"{self.provider_name} returned empty content")
        return content

    def _extract_content(self, message: Any) -> str:
        return message.content or ""


class MimoClient(_OpenAICompatibleClient):
    """OpenAI-compatible client for MiMo.

    The thinking-mode ``reasoning_content`` quirk is quarantined here, per ADR 0003: the answer is
    read from ``message.content`` and ``reasoning_content`` is never fed to the JSON parser. Keeping
    that handling inside this client is exactly what issue 0004 requires when the router lands.
    """

    provider_name: ProviderName = "mimo"

    def _extract_content(self, message: Any) -> str:
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None and getattr(message, "model_extra", None):
            reasoning = message.model_extra.get("reasoning_content")
        if reasoning:
            logger.debug("MiMo reasoning_content (%d chars) ignored for parsing", len(reasoning))
        return super()._extract_content(message)


class GroqClient(_OpenAICompatibleClient):
    """OpenAI-compatible client for Groq."""

    provider_name: ProviderName = "groq"


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
    ) -> str:
        primary = self._clients[self._primary_provider]
        try:
            return primary.chat(messages, response_format=response_format)
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
            return fallback.chat(messages, response_format=response_format)


def build_client(settings: Settings) -> LLMClient:
    """Return the routed LLM client selected by ``PRIMARY_PROVIDER``."""
    clients: dict[ProviderName, LLMClient] = {}
    mimo = settings.provider_config("mimo")
    if mimo.configured:
        clients["mimo"] = MimoClient(mimo)
    groq = settings.provider_config("groq")
    if groq.configured:
        clients["groq"] = GroqClient(groq)
    return LLMRouter(
        settings.primary_provider,
        clients,
        fallback_provider=settings.fallback_provider,
    )
