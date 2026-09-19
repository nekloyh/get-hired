"""The Session wire protocol: what a client may send, and who is allowed to send it.

Split out of ``web_api`` under GH #124. One reason to change: the shape of a frame on the socket, or
the rules for admitting one. The input bounds live here because they ARE the protocol — the largest
answer, the longest elapsed time, the biggest frame uvicorn will assemble.

Nothing here knows about a running Session (``web_runtime``) or the graph (``web_session_driver``).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from .config import Settings
from .ledger import SAFE_CANDIDATE_ID
from .supervisor import DEFAULT_MAX_ELAPSED_SECONDS, DEFAULT_MAX_QUESTIONS

logger = logging.getLogger(__name__)

SessionMode = Literal["auto", "demo", "live"]

# Input bounds (AUDIT §3.1): one client must not be able to grow memory or prompt cost without limit.
MAX_ANSWER_CHARS = 20_000
MAX_ELAPSED_SECONDS_CEILING = 4 * 3600.0
# The largest inbound WebSocket frame uvicorn will assemble before handing it to us. It has to live
# here with the other input bounds because nginx cannot supply it: `client_max_body_size` governs an
# HTTP request body, and after the 101 Upgrade the proxy is forwarding a byte stream — measured
# through the real compose stack on 2026-09-15, a 5,000,056-byte frame crossed nginx untouched and
# was refused only by `CandidateAnswerPayload`'s 20,000-character bound, i.e. after the whole frame
# had been buffered. uvicorn's own default is 16 MiB, and the deployment is deliberately
# single-worker (R-12), so that default is an attacker-controlled allocation times uvicorn's 32-deep
# queue. 256 KiB is ~12x the largest legitimate frame (a full-length answer is ~20 KB of JSON).
# Inbound only: frames this server SENDS (a `state_update` carrying the whole transcript) are bounded
# by the client's own limit, not this one.
WS_MAX_FRAME_BYTES = 256 * 1024


class StartSessionPayload(BaseModel):
    type: Literal["start_session"]
    mode: SessionMode = "auto"
    target_role: str = "machine learning engineer"
    target_companies: list[str] = Field(default_factory=list)
    claimed_skills: dict[str, float] = Field(default_factory=dict)
    # Cross-session Skill ledger id (0023); empty = one-shot cold start. A constrained KEY, not a
    # display name and not ownership: the shared token is one principal, so this cannot separate two
    # pilot users — that is R-29. Refusing loudly at the boundary is what keeps a bad id from
    # degrading into a silent cold start that then silently never saves (ADR 0005). The ^/$ anchors
    # are load-bearing: pydantic's `pattern` is a search, not a match, so unanchored it accepts
    # "minh/../../etc/passwd".
    candidate_id: str = Field("", pattern=rf"^$|^{SAFE_CANDIDATE_ID.pattern}$")
    max_questions: int = Field(DEFAULT_MAX_QUESTIONS, ge=1, le=10)
    max_elapsed_seconds: float = Field(DEFAULT_MAX_ELAPSED_SECONDS, gt=0, le=MAX_ELAPSED_SECONDS_CEILING)
    language_mode: Literal["en", "vn", "mixed"] = "en"  # issue 0024, ADR 0007


class ResumeSessionPayload(BaseModel):
    type: Literal["resume_session"]
    mode: SessionMode = "auto"


class CandidateAnswerPayload(BaseModel):
    type: Literal["candidate_answer"]
    answer: str = Field(max_length=MAX_ANSWER_CHARS)
    # NEW-01: which turn this answers. Nullable in the schema so a frame that omits it reaches the
    # handler and is REFUSED there with a Candidate-readable message, rather than dying as a raw
    # pydantic ValidationError — but it is required in effect: the handler rejects `None`.
    turn_id: int | None = None


class CancelSessionPayload(BaseModel):
    type: Literal["cancel_session"]


class AuthPayload(BaseModel):
    """The first frame a client sends when the server is gated (R-07).

    A frame rather than a query parameter on purpose: query strings land in access logs, proxy
    logs, and browser history, so `?token=` leaks the shared secret to every intermediary.
    """

    type: Literal["auth"]
    token: str = ""


ClientPayload = StartSessionPayload | ResumeSessionPayload | CandidateAnswerPayload | CancelSessionPayload | AuthPayload

# Browser origins allowed to open a Session socket when no allowlist is configured — the Vite dev
# server, matching what CORS already permitted before R-07.
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

# Hostnames that mean "this machine". An ungated server accepts a browser socket only from these, at
# any port, so the local dev workflow keeps working while a page on the open internet does not.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# How long a gated socket may stay open without authenticating. Without a deadline an unauthenticated
# connection holds a slot indefinitely — free denial of service against a single-worker deployment.
AUTH_FRAME_TIMEOUT_SECONDS = 10.0


def allowed_origins(settings: Settings) -> tuple[str, ...]:
    """Browser origins permitted to reach this API — one list for CORS and the WS handshake.

    ``*`` is refused, not honoured, because the two surfaces read it in opposite directions.
    ``CORSMiddleware`` takes it as "every origin" and, because ``allow_credentials`` is on, answers
    each request by echoing the caller's own Origin with a credentialed allow — so any page in the
    operator's browser can read a transcript export back. The WebSocket check compares it as a
    literal string, so the deployed UI is rejected anyway. An operator chasing the "will reject your
    deployed UI" warning reaches for ``*``, gets the same rejection they were already debugging, and
    never suspects what opened behind them. Refuse it at startup, where the cause is still visible,
    exactly as a non-ASCII ``COACH_AUTH_TOKEN`` is refused.
    """
    configured = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
    if "*" in configured:
        raise ValueError(
            "COACH_ALLOWED_ORIGINS must not contain `*`: CORS reads it as every origin and, with "
            "credentials allowed, hands any site that asks a readable copy of the transcript "
            "export, while the WebSocket Origin check compares it literally and rejects your own "
            "UI regardless. Set the exact origin serving the app, e.g. "
            "`COACH_ALLOWED_ORIGINS=https://coach.example.com` (comma-separated for more than one)."
        )
    return tuple(configured) if configured else DEFAULT_ALLOWED_ORIGINS


def _is_loopback_origin(origin: str) -> bool:
    try:
        host = urlparse(origin).hostname
    except ValueError:
        return False
    return host in LOOPBACK_HOSTS


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """Whether a WebSocket handshake carrying ``origin`` may proceed.

    A *missing* Origin passes. That is not a hole: Origin is set by the browser and cannot be forged
    or omitted by page JavaScript, so the cross-site hijack this guards against always carries one.
    Absent Origin means a non-browser client (curl, the test client, a native app), which the shared
    token — not this check — is what actually gates.

    An Origin is checked **whether or not a token is configured**. The same-origin policy does not
    apply to WebSockets, so any page the operator happens to visit can open a socket to
    ``ws://127.0.0.1:8000`` and drive a Session — start live interviews on the operator's API key,
    read the transcript back off the wire — without ever being on the local network. "Unset token =
    open" is a statement about *network* reach, not a licence for every site in the browser; on an
    ungated server the policy is therefore loopback-only, which keeps a dev server on any port
    working and shuts the drive-by out.
    """
    if origin is None:
        return True
    if not settings.auth_token:
        return _is_loopback_origin(origin)
    return origin in allowed_origins(settings)


def token_matches(candidate: str, settings: Settings) -> bool:
    """Constant-time comparison against the shared secret (never ``==`` on a credential).

    Compares UTF-8 *bytes*. ``compare_digest`` refuses ``str`` operands that are not ASCII-only —
    it raises ``TypeError`` rather than returning False — and ``candidate`` is attacker-controlled,
    so a client sending ``{"token": "café"}`` would otherwise crash the handler instead of being
    rejected. ``surrogatepass`` keeps that true for the lone surrogates a JSON body can carry.
    """
    return secrets.compare_digest(
        candidate.encode("utf-8", "surrogatepass"),
        settings.auth_token.encode("utf-8", "surrogatepass"),
    )


async def receive_json_frame(websocket: WebSocket) -> Any:
    """Read one client frame as JSON, normalising every malformed-frame failure to ``ValueError``.

    ``receive_json`` assumes a **text** frame: a binary one produces a message dict with no ``text``
    key and raises ``KeyError``, which is neither a disconnect nor a validation error, so it escapes
    the endpoint entirely — a traceback and an internal-error close for any client that sends binary
    JSON. On the pre-auth path that is an unauthenticated crash primitive; in the main loop it kills
    a live Session. One malformed frame is a client mistake, not a server fault.
    """
    try:
        return await websocket.receive_json()
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"expected a text frame containing JSON ({type(err).__name__}: {err})") from err


async def authenticate_socket(websocket: WebSocket, settings: Settings) -> bool:
    """Consume and check the client's opening auth frame. True when the socket may proceed."""
    if not settings.auth_token:
        return True
    try:
        raw = await asyncio.wait_for(receive_json_frame(websocket), timeout=AUTH_FRAME_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        return False
    if not isinstance(raw, dict) or raw.get("type") != "auth":
        return False
    return token_matches(str(raw.get("token", "")), settings)


# ADR 0005: cancellation is a control signal, never data. A distinct sentinel object put on the
# answers queue wakes a blocked read immediately and is unambiguous — a genuine empty-string answer
# ("") now flows through as data, where before it was indistinguishable from a cancel.


def _parse_payload(raw: Any) -> ClientPayload:
    if not isinstance(raw, dict):
        raise ValueError(f"expected a JSON object frame, got {type(raw).__name__}")
    payload_type = raw.get("type")
    model: type[BaseModel]
    if payload_type == "start_session":
        model = StartSessionPayload
    elif payload_type == "resume_session":
        model = ResumeSessionPayload
    elif payload_type == "candidate_answer":
        model = CandidateAnswerPayload
    elif payload_type == "cancel_session":
        model = CancelSessionPayload
    elif payload_type == "auth":
        model = AuthPayload
    else:
        raise ValueError(f"unknown WebSocket payload type: {payload_type!r}")
    try:
        return model.model_validate(raw)
    except ValidationError as err:
        raise ValueError(str(err)) from err


def _frame_refused(message: str) -> dict[str, Any]:
    """A refusal the socket loop keeps looping after — the one ``session_error`` that is not fatal.

    ``recoverable`` says exactly one thing, and a client may rely on nothing more: this FRAME was
    rejected and nothing else moved. The Session, its ``awaiting_turn_id`` and the graph thread parked
    in ``QueueCandidate.answer()`` are all untouched, so whatever the client applied optimistically
    when it sent the frame can be put back and the frame re-sent. The key is absent everywhere else on
    purpose: a refused start, a refused resume, a spent budget, a dead quota, a broken ledger, a cancel
    and a crash all leave nothing on this socket to retry. Absent therefore means terminal, which is
    what an older bundle already assumes for every error it sees.

    It cannot be inferred client-side: after an answer is queued the graph thread emits NO frame until
    the node finishes, so a provider crash while evaluating the answer just sent is indistinguishable
    from the socket loop refusing that same answer. A client guessing from timing would re-arm a turn
    the server has closed and hide the real fault behind a refuse/re-send loop.
    """
    return {"type": "session_error", "error": message, "recoverable": True}
