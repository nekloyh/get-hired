"""LLM access for slice 0001: a concrete MiMo client with validated structured output.

This is deliberately *not* the full provider router. Issue 0004 generalizes the call below into an
``LLMRouter`` (primary + failover, MiMo ↔ Groq via one env var). Agents depend only on the
:class:`LLMClient` protocol, so that refactor will not touch agent code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Message = dict[str, str]
Validator = Callable[[Any], None]


class StructuredOutputError(RuntimeError):
    """Raised when the model cannot produce schema-valid output within the retry budget."""


class LLMClient(Protocol):
    """The structural interface every agent depends on.

    Slice 0 ships only :class:`MimoClient`; issue 0004 adds a Groq client and a routing client
    (primary + failover) behind this same signature.
    """

    def chat_json(
        self,
        messages: Sequence[Message],
        response_model: type[T],
        *,
        validators: Sequence[Validator] = (),
        max_retries: int = 1,
    ) -> T: ...


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


class MimoClient:
    """OpenAI-compatible client for MiMo.

    The thinking-mode ``reasoning_content`` quirk is quarantined here, per ADR 0003: the answer is
    read from ``message.content`` and ``reasoning_content`` is never fed to the JSON parser. Keeping
    that handling inside this client is exactly what issue 0004 requires when the router lands.
    """

    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )

    def _complete(self, messages: Sequence[Message]) -> str:
        resp = self._client.chat.completions.create(
            model=self._settings.model,
            messages=list(messages),
            temperature=self._settings.temperature,
            response_format={"type": "json_object"},
        )
        message = resp.choices[0].message
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None and getattr(message, "model_extra", None):
            reasoning = message.model_extra.get("reasoning_content")
        if reasoning:
            logger.debug("MiMo reasoning_content (%d chars) ignored for parsing", len(reasoning))
        content = message.content or ""
        if not content.strip():
            raise ValueError("model returned empty content")
        return content

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
        ``validators``. On any failure it feeds the error back and retries up to ``max_retries``
        times before raising :class:`StructuredOutputError`.
        """
        convo = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            raw = ""
            try:
                raw = self._complete(convo)
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


def build_client(settings: Settings) -> LLMClient:
    """Return the active LLM client. Slice 0 always returns MiMo; issue 0004 makes this a router."""
    return MimoClient(settings)
