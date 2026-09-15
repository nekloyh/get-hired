"""FastAPI/WebSocket surface for the local React MVP."""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field, ValidationError
from starlette.status import WS_1008_POLICY_VIOLATION

from .concepts import (
    build_concept_store,
    embedder_for_language,
    embedder_persist_dir,
    resolve_concept_store_kind,
)
from .config import Settings, load_settings
from .demo_llm import DemoLLMClient
from .diagnostic import CandidateProfile, diagnose_or_degrade
from .exporter import export_session_markdown, render_session_markdown
from .language import DEFAULT_LANGUAGE_MODE
from .ledger import load_priors, save_posteriors
from .llm import UNKNOWN_PROVIDER, LLMClient, build_client, build_role_clients, provider_label
from .microloop import DEFAULT_MAX_TURNS, CandidateInputUnavailable, CandidateIntent
from .resources import build_resource_store
from .supervisor import (
    DEFAULT_MAX_ELAPSED_SECONDS,
    DEFAULT_MAX_QUESTIONS,
    SessionStatus,
    build_session_graph,
    initial_session_state,
    session_config,
    skill_states_from_state,
)
from .usage import (
    AccountingUnavailable,
    ProviderQuotaExhausted,
    SessionBudgetSuspended,
    begin_session_run,
    clear_run_rails_for_resume,
    daily_reset_hint,
    record_questions_released,
    reserve_questions,
    session_budget_guard,
    session_scope,
    start_refusal_reason,
    token_identity,
)

logger = logging.getLogger(__name__)

SessionMode = Literal["auto", "demo", "live"]

# Input bounds (AUDIT §3.1): one client must not be able to grow memory or prompt cost without limit.
MAX_ANSWER_CHARS = 20_000
MAX_ELAPSED_SECONDS_CEILING = 4 * 3600.0
ANSWER_QUEUE_MAXSIZE = 8

# How long a reconnect waits for the previous run's thread to leave an in-flight provider call. Covers
# one timed-out call plus a retry (LLM_TIMEOUT_SECONDS 60 x 2); a full 4-attempt retry storm can run
# ~4 minutes, in which case the client is told to retry rather than the wait growing to match.
STALE_RUNTIME_JOIN_SECONDS = 120.0

# Completed states kept in RAM; the export endpoint falls back to the Markdown `_persist_export` wrote.
MAX_COMPLETED_SESSIONS_IN_MEMORY = 64


class StartSessionPayload(BaseModel):
    type: Literal["start_session"]
    mode: SessionMode = "auto"
    target_role: str = "machine learning engineer"
    target_companies: list[str] = Field(default_factory=list)
    claimed_skills: dict[str, float] = Field(default_factory=dict)
    candidate_id: str = ""  # cross-session Skill ledger id (0023); empty = one-shot cold start
    max_questions: int = Field(DEFAULT_MAX_QUESTIONS, ge=1, le=10)
    max_elapsed_seconds: float = Field(DEFAULT_MAX_ELAPSED_SECONDS, gt=0, le=MAX_ELAPSED_SECONDS_CEILING)
    language_mode: Literal["en", "vn", "mixed"] = "en"  # issue 0024, ADR 0007


class ResumeSessionPayload(BaseModel):
    type: Literal["resume_session"]
    mode: SessionMode = "auto"


class CandidateAnswerPayload(BaseModel):
    type: Literal["candidate_answer"]
    answer: str = Field(max_length=MAX_ANSWER_CHARS)


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

# Completed-Session Markdown outlives the process here (R-08). The in-memory dict alone meant a
# restart ate every report that had not been downloaded yet, while the Session itself sat safely in
# the checkpoint DB — the one artifact the Candidate actually keeps was the one thing not persisted.
DEFAULT_EXPORTS_DIR = "data/exports"

# A Session id that is safe to use as a filename verbatim. Anything else gets digested (see
# ``export_path``) rather than rejected, so an unusual id still produces a report.
SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def allowed_origins(settings: Settings) -> tuple[str, ...]:
    """Browser origins permitted to reach this API — one list for CORS and the WS handshake."""
    configured = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
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
_CANCEL: Any = object()


class QueueCandidate:
    """Candidate bridge: graph thread emits a question, then waits for browser input."""

    def __init__(
        self,
        emit: EventEmitter,
        answers: queue.Queue[Any],
        cancelled: threading.Event,
    ) -> None:
        self._emit = emit
        self._answers = answers
        self._cancelled = cancelled

    def answer(self, question: str) -> str:
        self._emit({"type": "question", "question": question})
        while True:
            if self._cancelled.is_set():
                raise CandidateInputUnavailable("Session was cancelled while waiting for a Candidate answer.")
            try:
                item = self._answers.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is _CANCEL:
                raise CandidateInputUnavailable("Session was cancelled while waiting for a Candidate answer.")
            return item


@dataclass
class EventEmitter:
    loop: asyncio.AbstractEventLoop
    outgoing: asyncio.Queue[dict[str, Any]]

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, event)
        except RuntimeError:
            # The socket's event loop is gone (client disconnected, server shutting down). A background
            # graph thread unwinding a cancel/disconnect can reach here after teardown — the event has
            # nowhere to go, so drop it rather than crashing the thread.
            pass


def _bounded_answers() -> queue.Queue[Any]:
    return queue.Queue(maxsize=ANSWER_QUEUE_MAXSIZE)


@dataclass
class RuntimeSession:
    session_id: str
    mode: str
    emit: EventEmitter
    answers: queue.Queue[Any] = field(default_factory=_bounded_answers)
    cancelled: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    socket_closed: bool = False
    # Set under the state lock by the thread's own finally — unlike `is_alive()`, it cannot read
    # True for a thread that has already released the registration.
    run_finished: bool = False

    def reset_run_state(self) -> None:
        # A single socket can run start -> cancel -> start again. Without a fresh queue and event the
        # second run inherits a permanently-set cancelled flag (aborts instantly) and a stale sentinel
        # left in the queue (consumed as the first answer). Reset before each run.
        self.answers = _bounded_answers()
        self.cancelled = threading.Event()
        self.run_finished = False

    @property
    def run_in_flight(self) -> bool:
        return self.thread is not None and not self.run_finished

    def cancel(self) -> None:
        # A cancel supersedes queued answers: drain so the sentinel can never be lost to a full queue.
        self.cancelled.set()
        with suppress(queue.Empty):
            while True:
                self.answers.get_nowait()
        self.answers.put_nowait(_CANCEL)

    def start(self, target, *args: Any) -> None:
        self.thread = threading.Thread(target=target, args=args, daemon=True)
        self.thread.start()


@dataclass
class WebApiState:
    settings: Settings
    checkpoint_db: str
    ledger_db: str = ".skill-ledger.json"
    exports_dir: str = DEFAULT_EXPORTS_DIR
    completed_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    runtimes: dict[str, RuntimeSession] = field(default_factory=dict)
    # Session ids with a reconnect currently waiting for the previous run's thread: one waiter per id.
    waiting: set[str] = field(default_factory=set)
    # Guards every read/write of `runtimes`, `waiting`, and the eviction in `completed_sessions`.
    lock: threading.Lock = field(default_factory=threading.Lock)


def export_path(exports_dir: str | Path, session_id: str) -> Path:
    """Where a completed Session's Markdown lives on disk.

    The Session id is client-supplied — it arrives as a URL path segment — so it is never
    interpolated into a filename unchecked: ``../../.ssh/authorized_keys`` would otherwise be a
    write primitive on completion and a read primitive on export. Ids that are already safe (the
    UUIDs R-06 generates) keep their own name so the directory stays greppable by a human; anything
    else is replaced by a digest, which cannot collide and cannot escape the directory.
    """
    base = Path(exports_dir)
    safe = session_id if SAFE_SESSION_ID.fullmatch(session_id) else sha256(session_id.encode("utf-8")).hexdigest()
    return base / f"{safe}.md"


def _validate_auth_settings(settings: Settings) -> None:
    """Refuse to start on a shared secret that cannot survive the wire.

    HTTP header values are latin-1 on the wire, so a non-ASCII ``COACH_AUTH_TOKEN`` can never
    round-trip through ``Authorization: Bearer`` — the operator would lock themselves out of their
    own export endpoint with no error that names the cause. A Vietnamese passphrase is the obvious
    thing to reach for here, which is exactly why this fails loudly at startup instead.
    """
    if settings.auth_token and not settings.auth_token.isascii():
        raise ValueError(
            "COACH_AUTH_TOKEN must be ASCII: HTTP headers are latin-1 on the wire, so a non-ASCII "
            "token cannot round-trip through `Authorization: Bearer` and would reject the operator "
            "along with everyone else. Generate one with `openssl rand -hex 32`."
        )


def _requested_workers(env: Mapping[str, str], argv: Sequence[str]) -> tuple[int, str] | None:
    """The worker count that will actually take effect, and which channel set it, or None.

    Resolution mirrors uvicorn's exactly, because a guard that reads the command line differently
    from the launcher is worse than no guard: it both misses and misfires. uvicorn's ``--workers``
    is a plain click option (no ``multiple=True``), so a repeated flag keeps the **last** value —
    stopping at the first occurrence let ``--workers 1 --workers 4`` start four processes silently,
    and refused ``--workers 4 --workers 1`` with advice the operator had already taken. And
    ``Config`` consults ``WEB_CONCURRENCY`` only ``if workers is None``, so any explicit flag —
    including a typo uvicorn is about to reject — shadows the environment.

    A value that is not an integer is uvicorn's own error to report; raising ``ValueError`` on a
    typo would be a worse failure than the one this guard exists to prevent.
    """
    flagged: str | None = None
    for index, token in enumerate(argv):
        if token.startswith("--workers="):
            flagged = token[len("--workers=") :]
        elif token == "--workers" and index + 1 < len(argv):
            flagged = argv[index + 1]
    if flagged is not None:
        with suppress(ValueError):
            return int(flagged), "--workers"
        # Unparseable, but still explicit — and click rejects it before ``Config`` ever reads the
        # environment. Falling through would refuse the run over a variable that is not in play.
        return None
    with suppress(ValueError, KeyError):
        return int(env["WEB_CONCURRENCY"]), "WEB_CONCURRENCY"
    return None


def guard_single_worker(env: Mapping[str, str] | None = None, argv: Sequence[str] | None = None) -> None:
    """Refuse to serve from more than one process, before a socket is bound or a worker forked.

    Called at module import rather than only from ``coach api`` because the CLI is not the only way
    in: ``uvicorn interview_coach.web_api:app --workers 4`` never touches it. Under uvicorn, import
    time is early enough — the launcher is still in ``config.load_app()``, which runs *before*
    ``bind_socket()`` and before ``Multiprocess(...)``, so raising here kills it rather than
    half-starting a fleet. That "before the port" property is uvicorn's, not universal: gunicorn's
    default ``preload_app=False`` binds and logs ``Listening at:`` before it forks and imports, so
    the guard would only fire inside the children. gunicorn is not a dependency and not in the image,
    so that is a documented limit rather than a case to engineer for. ``WEB_CONCURRENCY`` is checked
    because it is the route nobody types: compose feeds `.env` into the container wholesale and
    uvicorn resolves the variable itself.

    A hard failure, not a degrade. ADR 0005's degrade stance protects skill evidence from
    infrastructure noise; this fires before any Session exists, so there is no evidence to protect
    and a warning would buy silently-lost interviews instead.
    """
    requested = _requested_workers(env if env is not None else os.environ, argv if argv is not None else sys.argv)
    if requested is None:
        return
    workers, channel = requested
    if workers <= 1:
        return
    fix = f"drop {channel}" if channel.startswith("--") else f"unset {channel}"
    raise RuntimeError(
        f"{channel}={workers} asks for {workers} worker processes; this server supports exactly one. "
        "`runtimes` and `completed_sessions` are per-process dicts and the checkpoint store is a "
        "single SQLite file, so a second worker would answer a reconnect for a Session it has never "
        f"heard of while two processes write one checkpoint DB. Run exactly one worker ({fix}, or "
        "set it to 1). See docs/deploy.md §6; scaling past one host is R-29."
    )


def configure_session_logging(log_file: str = "") -> None:
    """Make the per-call ``llm-call`` trace visible in whichever process actually serves requests.

    Uvicorn configures logging in the **worker**, and under ``--reload`` that worker is a freshly
    spawned process where the CLI's own ``basicConfig`` never ran. Uvicorn attaches handlers to its
    own loggers only, so ``interview_coach`` records reach a bare root logger and die at WARNING —
    silently, and only in reload mode, which makes the trace look flaky rather than unconfigured.
    R-26's trace is how a silent judge failover is caught after the fact (ADR 0009 addendum a), so
    it has to survive every way this app gets started. Module import is the one hook that runs in
    the serving process either way.

    ``log_file`` is what makes that trace outlive a container restart. It arrives through the
    environment (``COACH_LOG_FILE``, like ``COACH_USAGE_LEDGER``) rather than ``Settings`` for the
    same spawned-subprocess reason as above, and so that logging is up before Settings validation
    can raise on something unrelated.
    """
    log = logging.getLogger("interview_coach")
    log.setLevel(logging.INFO)
    formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
    # Only self-configure when nothing else will emit these records; the CLI's basicConfig installs
    # a root handler, and adding a second one here would print every line twice.
    if not log.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        log.addHandler(handler)
    if not log_file.strip():
        return
    try:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    except OSError:
        # ADR 0005's degrade side, applied to a support concern: an unwritable log path is a reason
        # to lose the file sink, never a reason for a working deployment to refuse to come back up.
        logger.warning("COACH_LOG_FILE=%s is not writable; logging to stderr only", log_file, exc_info=True)
        return
    rotating.setFormatter(formatter)
    log.addHandler(rotating)


def prune_checkpoints(checkpointer: Any, *, max_age_seconds: float, now: float) -> list[str]:
    """Drop checkpoint threads whose newest checkpoint is older than ``max_age_seconds``.

    The checkpoint DB had no reaper of any kind: every Session ever started stayed in it for the life
    of the deployment, on a single-file SQLite that also serves live resume.

    A **TTL sweep, not delete-on-completion.** Dropping a thread the moment its Session completes
    looks tidier and is the first option the issue offers, but it breaks a path that works today:
    reconnecting to a finished Session currently replays its final checkpoint and re-emits the
    report (measured, not assumed). With the thread gone, that resume finds nothing and fails. The
    TTL keeps recently-finished Sessions resumable and still bounds growth, which was the actual
    complaint.

    Best-effort by design: a cleanup that cannot read one thread's timestamp must not stop the
    server from starting, so unparseable rows are left alone rather than guessed at.
    """
    newest: dict[str, float] = {}
    try:
        for entry in checkpointer.list(None):
            thread_id = entry.config.get("configurable", {}).get("thread_id")
            stamp = _checkpoint_timestamp(entry.checkpoint.get("ts"))
            if thread_id is None or stamp is None:
                continue
            newest[thread_id] = max(newest.get(thread_id, stamp), stamp)
    except Exception:
        logger.warning("could not enumerate checkpoint threads; skipping the sweep", exc_info=True)
        return []
    pruned = []
    for thread_id, stamp in sorted(newest.items()):
        if now - stamp <= max_age_seconds:
            continue
        try:
            checkpointer.delete_thread(thread_id)
        except Exception:
            # %r: a checkpoint thread id *is* a Session id, so this string came from a URL path
            # segment however indirectly — a round trip through SQLite launders nothing.
            logger.warning("could not prune checkpoint thread %r", thread_id, exc_info=True)
            continue
        pruned.append(thread_id)
    if pruned:
        logger.info("pruned %d checkpoint thread(s) older than %.0fs", len(pruned), max_age_seconds)
    return pruned


def _checkpoint_timestamp(raw: Any) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def create_app(
    *,
    settings: Settings | None = None,
    checkpoint_db: str | Path | None = None,
    ledger_db: str | Path | None = None,
    exports_dir: str | Path | None = None,
    static_dir: str | Path | None = None,
) -> FastAPI:
    # Explicit arguments win (tests pin every path under tmp_path); otherwise the environment
    # decides, so a container can put all three on one mounted volume without a code change.
    resolved = settings or load_settings()
    api_state = WebApiState(
        settings=resolved,
        checkpoint_db=str(checkpoint_db if checkpoint_db is not None else resolved.checkpoint_db),
        ledger_db=str(ledger_db if ledger_db is not None else resolved.ledger_db),
        exports_dir=str(exports_dir if exports_dir is not None else resolved.exports_dir),
    )
    _validate_auth_settings(api_state.settings)
    app = FastAPI(title="Adaptive Interview Coach API")
    app.state.web_api = api_state
    origins = allowed_origins(api_state.settings)
    if not api_state.settings.auth_token:
        logger.warning(
            "COACH_AUTH_TOKEN is unset: every endpoint is OPEN to anything that can reach this "
            "port (browser sockets are restricted to localhost origins). Fine on localhost, unsafe "
            "anywhere reachable — set it before exposing this."
        )
    elif not api_state.settings.allowed_origins.strip():
        # Gated but no allowlist: the WS handshake falls back to the Vite dev origins, so the
        # deployment's own UI gets rejected while `http://localhost:5173` is trusted. Silent in the
        # logs this reads as "auth is broken"; it is a missing env var.
        logger.warning(
            "COACH_AUTH_TOKEN is set but COACH_ALLOWED_ORIGINS is empty: browser sockets are "
            "restricted to the dev-server origins %s, which will reject your deployed UI. Set "
            "COACH_ALLOWED_ORIGINS to the origin serving the app.",
            ", ".join(DEFAULT_ALLOWED_ORIGINS),
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "primary_provider": api_state.settings.primary_provider,
            "primary_configured": api_state.settings.configured,
            "fallback_provider": api_state.settings.fallback_provider,
            "fallback_configured": api_state.settings.fallback_config.configured,
            "demo_available": True,
            # Lets the UI ask for the shared secret at runtime instead of being built with it baked
            # in. Advertising *that* a gate exists discloses nothing an unauthorized 401 would not.
            "auth_required": bool(api_state.settings.auth_token),
            # R-13: the UI banners a degraded retrieval path rather than letting it be invisible —
            # every published retrieval number describes Chroma, not the keyword ranker.
            "concept_store": resolve_concept_store_kind(api_state.settings.concept_store),
            "retrieval_degraded": resolve_concept_store_kind(api_state.settings.concept_store) == "memory",
        }

    @app.websocket("/api/sessions/{session_id}")
    async def session_socket(websocket: WebSocket, session_id: str) -> None:
        # Origin is checked BEFORE accept(): a rejected cross-site handshake must never become a
        # live socket, and CORSMiddleware cannot do this — it does not see WebSocket handshakes at
        # all, which is why the pre-R-07 CORS config guarded nothing here.
        if not origin_allowed(websocket.headers.get("origin"), api_state.settings):
            logger.warning("rejected WebSocket handshake from disallowed origin %r", websocket.headers.get("origin"))
            await websocket.close(code=WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        if not await authenticate_socket(websocket, api_state.settings):
            logger.warning("rejected WebSocket connection: missing or invalid auth frame")
            await websocket.close(code=WS_1008_POLICY_VIOLATION)
            return
        outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        emit = EventEmitter(asyncio.get_running_loop(), outgoing)
        runtime = RuntimeSession(session_id=session_id, mode="pending", emit=emit)
        # One live socket per Session id, and one graph per checkpoint thread: a second tab is
        # refused, and a reconnect waits for the previous run's thread before it may resume.
        if (refusal := await _claim_session_id(api_state, session_id, runtime)) is not None:
            await websocket.send_json({"type": "session_error", "error": refusal})
            await websocket.close()
            return
        sender = asyncio.create_task(_send_events(websocket, outgoing))
        # %r, not %s — and the same for every other Session-id record in this module: the id is a
        # client-supplied URL path segment that Starlette percent-decodes, so `%0A` in it would forge
        # whole log lines. Same untrusted-input care `export_path` takes with the filesystem.
        logger.info("Session %r socket connected", session_id)
        try:
            while True:
                try:
                    payload = _parse_payload(await receive_json_frame(websocket))
                except ValueError as err:
                    emit({"type": "session_error", "error": str(err)})
                    continue
                if isinstance(payload, StartSessionPayload):
                    if _is_running(runtime):
                        emit({"type": "session_error", "error": "A Session is already running on this socket."})
                        continue
                    runtime.reset_run_state()
                    runtime.mode = _select_mode(payload.mode, api_state.settings)
                    runtime.start(
                        _run_session_thread,
                        api_state,
                        runtime,
                        payload,
                        False,
                    )
                elif isinstance(payload, ResumeSessionPayload):
                    if _is_running(runtime):
                        emit({"type": "session_error", "error": "A Session is already running on this socket."})
                        continue
                    runtime.reset_run_state()
                    runtime.mode = _select_mode(payload.mode, api_state.settings)
                    runtime.start(
                        _run_session_thread,
                        api_state,
                        runtime,
                        payload,
                        True,
                    )
                elif isinstance(payload, AuthPayload):
                    # Already authenticated (or the server is ungated) — a repeat auth frame is a
                    # harmless no-op rather than an "unknown payload type" error, so a client that
                    # always sends one works against gated and open servers alike.
                    continue
                elif isinstance(payload, CandidateAnswerPayload):
                    try:
                        runtime.answers.put_nowait(payload.answer)
                    except queue.Full:
                        emit(
                            {
                                "type": "session_error",
                                "error": "Answer dropped: earlier answers are still being processed.",
                            }
                        )
                else:
                    # Cancel is a control signal (ADR 0005): flag it and drop the sentinel so a blocked
                    # QueueCandidate.answer() raises CandidateIntent. _run_session_thread emits the
                    # terminal event; no "" is injected as a fake answer.
                    runtime.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            # Whatever ended this socket — disconnect, cancel, or a bug in the loop above — the run
            # must be told, or a thread nobody feeds would hold the registration forever.
            runtime.cancel()
            sender.cancel()
            with api_state.lock:
                runtime.socket_closed = True
                # A thread still inside a provider call keeps the registration; it pops itself when
                # it exits, so a reconnect on this id waits instead of starting a second graph.
                if api_state.runtimes.get(session_id) is runtime and not runtime.run_in_flight:
                    api_state.runtimes.pop(session_id, None)

    @app.get("/api/sessions/{session_id}/export.md", response_class=PlainTextResponse)
    def export_markdown(session_id: str, authorization: str = Header(default="")) -> str:
        # The export is the whole transcript — the most disclosure-sensitive thing this API serves.
        if api_state.settings.auth_token:
            scheme, _, presented = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token_matches(presented.strip(), api_state.settings):
                raise HTTPException(
                    status_code=401,
                    detail="Missing or invalid bearer token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        state = api_state.completed_sessions.get(session_id)
        if state is not None:
            if state.get("status") != SessionStatus.COMPLETE.value:
                # In memory but unfinished: a cancelled or errored run. Saying "not complete yet" is
                # more useful than falling through to a 404 that implies it never existed.
                raise HTTPException(status_code=409, detail="Session is not complete yet.")
            return render_session_markdown(state)
        # Not in this process's memory — which after any restart is every Session ever completed.
        stored = export_path(api_state.exports_dir, session_id)
        try:
            return stored.read_text(encoding="utf-8")
        except OSError:
            raise HTTPException(status_code=404, detail="No completed Session found for this Session id.") from None

    _sweep_checkpoints_at_startup(api_state)
    # Registered last, deliberately: a mount at "/" matches everything, so every API route above has
    # to be in the table already or the UI would swallow them.
    _mount_static_ui(app, static_dir if static_dir is not None else resolved.static_dir)
    return app


def _sweep_checkpoints_at_startup(api_state: WebApiState) -> None:
    """Reap stale checkpoint threads once, at app construction — the DB had no reaper at all."""
    ttl = api_state.settings.checkpoint_ttl_seconds
    if ttl <= 0:
        return
    try:
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer:
            prune_checkpoints(checkpointer, max_age_seconds=ttl, now=time.time())
    except Exception:
        # A cleanup must never be the reason the server fails to start.
        logger.warning("checkpoint sweep failed at startup", exc_info=True)


def _mount_static_ui(app: FastAPI, static_dir: str | Path) -> None:
    """Serve the built React bundle from this app when one is present.

    Optional, because the dev setup has Vite serving the UI on its own port. In a container it is
    what collapses UI and API onto **one origin**: same-origin means the bundle needs no baked-in
    API host, the WebSocket inherits the page's scheme (so `wss://` follows `https://` for free),
    and there is no cross-origin handshake for CORS or the Origin allowlist to adjudicate.
    """
    if not str(static_dir).strip():
        return
    directory = Path(static_dir)
    if not (directory / "index.html").is_file():
        logger.warning(
            "COACH_STATIC_DIR=%s has no index.html; serving the API only. Did `npm run build` run?",
            directory,
        )
        return
    app.mount("/", StaticFiles(directory=directory, html=True), name="ui")
    logger.info("serving the built UI from %s", directory)


guard_single_worker()
configure_session_logging(os.environ.get("COACH_LOG_FILE", ""))

# `app` is built on first access, not at import: importing this module must not read `.env`, open
# and sweep the checkpoint DB, or mount static files. `uvicorn interview_coach.web_api:app` still works.
_lazy_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    global _lazy_app
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _lazy_app is None:
        _lazy_app = create_app()
    return _lazy_app


async def _send_events(websocket: WebSocket, outgoing: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        event = await outgoing.get()
        await websocket.send_json(event)


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


def _is_running(runtime: RuntimeSession) -> bool:
    return runtime.thread is not None and runtime.thread.is_alive()


def _select_mode(mode: SessionMode, settings: Settings) -> str:
    if mode == "demo":
        return "demo"
    if mode == "live":
        return "live"
    return "live" if settings.configured else "demo"


def _client_for_mode(mode: str, settings: Settings) -> LLMClient:
    if mode == "demo":
        return DemoLLMClient()
    if not settings.configured:
        raise RuntimeError(
            f"LLM primary provider {settings.primary_provider!r} is not configured; use demo mode or configure .env."
        )
    return build_client(settings)


def _run_session_thread(
    api_state: WebApiState,
    runtime: RuntimeSession,
    payload: StartSessionPayload | ResumeSessionPayload,
    resume: bool,
) -> None:
    # QA-08: what this run took off the daily question cap, so the `finally` can hand back what it
    # can never ask. Declared outside the `try`, because the first statement inside it can raise.
    reservation: tuple[str, int] | None = None
    try:
        # QA-01: a fresh start on an id that already has a checkpoint restarts the graph over it AND
        # overwrites exports/<id>.md, which the export endpoint can never get back — it reads RAM,
        # then that file, never the checkpoint. The browser keeps ONE id in localStorage
        # (web/src/lib/sessionId.ts) and renders it read-only, so a returning Candidate pressing
        # Start is exactly this case, not an edge case. Refuse it before anything is built or spent;
        # resuming and rotating the id are both one click away.
        if not resume and _checkpoint_values(api_state, runtime.session_id):
            logger.warning("refused a fresh start on Session %r: it already has a checkpoint", runtime.session_id)
            runtime.emit({"type": "session_error", "error": _ALREADY_CHECKPOINTED})
            return
        client = _client_for_mode(runtime.mode, api_state.settings)
        # ADR 0010: demo mode's client is not a router, so the bundle collapses to single-client
        # semantics; live mode pins the judge and applies any ROLE_* overrides.
        roles = build_role_clients(api_state.settings, client)
        # R-25: the free-tier rails, checked before ANY token is spent. A client with no provider
        # identity (demo mode, test fakes) spends nobody's allowance, so both gates are inert for it.
        provider = provider_label(roles.judge)
        metered = provider != UNKNOWN_PROVIDER
        checkpoint_values = _checkpoint_values(api_state, runtime.session_id) if resume else {}
        if resume and not checkpoint_values:
            # The CLI's --resume guard, ported (issue 0019). With nothing checkpointed,
            # graph.stream(None, ...) answers with langgraph's EmptyInputError, which reached the
            # Candidate as `session_error: EmptyInputError: Received no input for __start__`. Not an
            # edge case: the browser keeps one Session id in localStorage forever while checkpoints
            # expire on COACH_CHECKPOINT_TTL_SECONDS (7 days), so a Candidate returning after the
            # sweep clicks the UI's own "Reconnect & Resume" and is hard-stuck on a message about
            # `__start__`. Refused ABOVE the resume budget-rail clearing, which writes to the usage
            # ledger, and BEFORE `session_started` — the reducer appends "Session resumed from
            # checkpoint." on that frame, so emitting it here tells the Candidate their progress was
            # restored and then hands them the error.
            logger.warning("refused to resume Session %r: no checkpoint", runtime.session_id)
            runtime.emit({"type": "session_error", "error": _unknown_session_message(runtime.session_id)})
            return
        # QA-08: built HERE, before the cap reservation below, because building it is what rejects an
        # unknown Skill claim. Reserving first let 48 malformed frames at max_questions=10 fill a
        # 480-question cap for the whole UTC day at zero provider cost, and a client that crashes
        # between the two did the same by accident.
        profile: CandidateProfile | None = None
        if not resume:
            assert isinstance(payload, StartSessionPayload)
            profile = CandidateProfile(
                target_role=payload.target_role,
                target_companies=tuple(payload.target_companies),
                claimed_skills=payload.claimed_skills,
            )
        max_questions = (
            int(checkpoint_values.get("max_questions", DEFAULT_MAX_QUESTIONS))
            if resume
            else cast("StartSessionPayload", payload).max_questions
        )
        if metered and not resume:
            assert isinstance(payload, StartSessionPayload)
            identity = token_identity(api_state.settings.auth_token)
            # Budget rail first (read-only), then the cap: reserved at START, not at completion (a
            # cap that only counts finished Sessions is bypassed by abandoning them), check+record in
            # one locked step, and never consumed by a start the budget rail already refused.
            refusal = start_refusal_reason(provider, questions=payload.max_questions) or reserve_questions(
                identity, questions=payload.max_questions
            )
            if refusal is not None:
                # No `session_started`: the Candidate must never watch an interview begin that
                # cannot be paid for.
                logger.warning("refused to start Session %r: %s", runtime.session_id, refusal)
                runtime.emit({"type": "session_error", "error": refusal})
                return
            reservation = (identity, payload.max_questions)
        if metered and resume:
            # The Candidate clicked resume. The per-run ceiling and the insufficient_quota latch
            # both hang on this run's own state, so nothing but this clears them — and a resume
            # that cannot clear them re-suspends at stream event 0 forever, which is the stall
            # ADR 0005 forbids and which a Candidate with no shell has no way around.
            if cleared := clear_run_rails_for_resume(
                runtime.session_id,
                provider,
                max_questions=max_questions,
                max_turns=DEFAULT_MAX_TURNS,
            ):
                logger.warning("Session %r resumed past a budget stop: %s", runtime.session_id, cleared)
        # R-13: the measured path is the default path. Demo mode stays in-memory on purpose — it
        # runs on a fake model for UX review, and building a Chroma index (first run: downloading an
        # embedding model) to serve fake questions would be a slow answer to a question nobody asked.
        # R-14: the embedder follows the Session's language. BGE is English-only and collapses
        # Vietnamese onto a hub, so a vn/mixed Session retrieving with it ranks near-randomly.
        language_mode = _session_language_mode(payload, resume, checkpoint_values)
        embedder = embedder_for_language(language_mode)
        concept_store = build_concept_store(
            "memory" if runtime.mode == "demo" else api_state.settings.concept_store,
            persist_dir=embedder_persist_dir(api_state.settings.concept_persist_dir or None, embedder),
            seed=True,
            embedding_model=embedder,
        )
        resource_store = build_resource_store("memory", seed=True)

        # The same guard the CLI installs, built from the same factory — the two surfaces must not
        # be able to disagree about when a Session suspends or what it is told.
        budget_stop = (
            session_budget_guard(
                runtime.session_id,
                provider,
                max_turns=DEFAULT_MAX_TURNS,
                complete_status=SessionStatus.COMPLETE.value,
            )
            if metered
            else None
        )

        # The scope attributes every provider call this Session makes — the graph runs on this same
        # thread, so the ContextVar reaches every node.
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer, session_scope(runtime.session_id):
            graph = build_session_graph(
                roles,
                checkpointer=checkpointer,
                concept_store=concept_store,
                resource_store=resource_store,
                candidate_factory=lambda seed: QueueCandidate(runtime.emit, runtime.answers, runtime.cancelled),
            )
            config = session_config(runtime.session_id)
            initial_state = None
            if not resume:
                assert isinstance(payload, StartSessionPayload)
                if metered:
                    # Stamp this run's baseline before the Diagnostic spends anything. The browser
                    # persists ONE Session id in localStorage and reuses it for every fresh start
                    # until the Candidate asks for a new one, so without a baseline the rail would
                    # charge each new interview for every interview that came before it.
                    begin_session_run(runtime.session_id)
                assert profile is not None  # built above, before the cap reservation (QA-08)
                carried = load_priors(api_state.ledger_db, payload.candidate_id, now=time.time())
                diagnostic = diagnose_or_degrade(
                    profile,
                    roles.diagnostic,
                    ledger_priors=carried.seed_means if carried else None,
                )
                initial_state = initial_session_state(
                    runtime.session_id,
                    diagnostic,
                    max_questions=payload.max_questions,
                    max_elapsed_seconds=payload.max_elapsed_seconds,
                    candidate_id=payload.candidate_id,
                    ledger_prior_mastery=carried.raw_mastery if carried else None,
                    language_mode=payload.language_mode,
                )
            runtime.emit(
                {
                    "type": "session_started",
                    "session_id": runtime.session_id,
                    "mode": runtime.mode,
                    "resumed": resume,
                }
            )
            final_state = _stream_graph(graph, initial_state, config, runtime, budget_stop=budget_stop)
        if final_state is not None:
            # Persist posteriors for a returning Candidate (0023); candidate_id rides in the state so a
            # resumed Session saves too. save_posteriors no-ops on an empty id. The Markdown is written
            # BEFORE the state enters the bounded RAM cache, so an evicted id always has its file.
            if final_state.get("status") == SessionStatus.COMPLETE.value:
                _persist_export(api_state, runtime.session_id, final_state)
                save_posteriors(
                    api_state.ledger_db,
                    str(final_state.get("candidate_id", "")),
                    skill_states_from_state(final_state),
                    now=time.time(),
                )
            _remember_completed(api_state, runtime.session_id, final_state)
            # Logged before the emit, not after: the emit is what hands control to the client, and a
            # record written afterwards races the browser (and the test) that is already reacting.
            logger.info("Session %r finished: status=%s", runtime.session_id, final_state.get("status"))
            runtime.emit({"type": "session_completed", "state": final_state})
    except SessionBudgetSuspended as err:
        # ADR 0005's third category: budget exhaustion. Its own branch, ABOVE the completion block —
        # a suspended Session must never emit session_completed or be persisted as if it finished.
        # The checkpoint is durable, so the UI's resume picks it up once the budget allows.
        logger.warning("Session %r suspended on a budget rail: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session suspended: {err}"})
    except ProviderQuotaExhausted as err:
        # GH #119: the daily quota died mid-Session. Same structural reason as the branch above —
        # nothing completed, so nothing is persisted as complete; the checkpoint stays resumable.
        logger.warning("Session %r suspended on a dead provider quota: %s", runtime.session_id, err)
        # A quota that dies on the Diagnostic leaves no checkpoint; offering a resume would be a stall.
        next_step = (
            "Resuming re-tries the provider once."
            if _checkpoint_values(api_state, runtime.session_id)
            else "Nothing was checkpointed yet; start a new Session after the reset."
        )
        runtime.emit({"type": "session_error", "error": f"Session suspended: {err} {daily_reset_hint()} {next_step}"})
    except AccountingUnavailable as err:
        # M0a / F1: a metered call was refused because usage accounting is broken or unreconciled.
        # Its own branch for the same structural reason as the one above — nothing completed, so
        # nothing may be persisted as complete — but a different remedy, which the Candidate-facing
        # text has to carry honestly: this one waits on an operator, not on 00:00 UTC.
        logger.error("Session %r stopped on an accounting fault: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session stopped: {err}"})
    except CandidateIntent as err:
        # ADR 0005 / issue 0017: the Candidate asked to stop (web cancel/disconnect). This is intent,
        # not an infrastructure failure — a distinct control-flow branch. The supervisor re-raises it
        # past the per-question failure-isolation net, so the in-flight question is never recorded as a
        # zero-evidence `failed` and the checkpoint stays resumable. Report it, don't score anything.
        logger.info("Session %r cancelled by Candidate intent: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session cancelled: {err}"})
    except Exception as err:  # noqa: BLE001 - API boundary converts graph/provider failures to events
        logger.exception("Session %r failed", runtime.session_id)
        runtime.emit({"type": "session_error", "error": f"{type(err).__name__}: {err}"})
    finally:
        # Outside the state lock on purpose: this reads the checkpoint DB and appends to the ledger,
        # and `_claim_session_id` and the socket handler are both blocked while that lock is held.
        _release_unused_questions(api_state, runtime, reservation)
        with api_state.lock:
            runtime.run_finished = True
            # The socket closed while this thread was still running: the registration was left for
            # this thread to release, so a waiting reconnect can now proceed.
            if runtime.socket_closed and api_state.runtimes.get(runtime.session_id) is runtime:
                api_state.runtimes.pop(runtime.session_id, None)


_ACTIVE_ELSEWHERE = "This Session id already has an active connection."
_STILL_FINISHING = "The previous run of this Session is still finishing; retry in a moment."
_ALREADY_CHECKPOINTED = (
    "This Session id already has saved progress. Resume it to continue where you left off, or use "
    '"New session" to get a fresh id — starting over here would overwrite the saved report.'
)


async def _claim_session_id(api_state: WebApiState, session_id: str, runtime: RuntimeSession) -> str | None:
    """Register ``runtime`` for ``session_id``; returns the refusal message when the id is taken."""
    with api_state.lock:
        stale = api_state.runtimes.get(session_id)
        if stale is None:
            api_state.runtimes[session_id] = runtime
            return None
        if not stale.socket_closed:
            return _ACTIVE_ELSEWHERE
        if session_id in api_state.waiting:
            # One waiter per id: a second reconnect must not pin another executor thread on the join.
            return _STILL_FINISHING
        api_state.waiting.add(session_id)
    try:
        if stale.thread is not None and stale.thread.is_alive():
            # Closed socket, thread still winding down: cancellation is already signalled, so the only
            # long wait is an in-flight provider call.
            await asyncio.get_running_loop().run_in_executor(None, stale.thread.join, STALE_RUNTIME_JOIN_SECONDS)
            if stale.thread.is_alive():
                return _STILL_FINISHING
        with api_state.lock:
            current = api_state.runtimes.get(session_id)
            if current is not None and current is not stale:
                # Someone else took the id while we waited: refuse if their socket is open OR their
                # run is still in flight — replacing either would put two graphs on one checkpoint.
                if not current.socket_closed:
                    return _ACTIVE_ELSEWHERE
                if current.run_in_flight:
                    return _STILL_FINISHING
            api_state.runtimes[session_id] = runtime
            return None
    finally:
        with api_state.lock:
            api_state.waiting.discard(session_id)


def _remember_completed(api_state: WebApiState, session_id: str, state: dict[str, Any]) -> None:
    """Keep the newest completed states in RAM, evicting the oldest past the cap."""
    with api_state.lock:
        completed = api_state.completed_sessions
        completed.pop(session_id, None)
        completed[session_id] = state
        while len(completed) > MAX_COMPLETED_SESSIONS_IN_MEMORY:
            del completed[next(iter(completed))]


def _release_unused_questions(
    api_state: WebApiState, runtime: RuntimeSession, reservation: tuple[str, int] | None
) -> None:
    """Hand back the questions this run reserved and can never ask (QA-08).

    Only a run that can never come back for them. A cancelled or SUSPENDED Session keeps a resumable
    checkpoint and a resume does not re-reserve — ``reserve_questions`` is on the ``not resume``
    branch — so releasing there would hand the resumed run its remaining questions off the books, and
    it would reopen the bypass the up-front reservation exists to close: a cap that only counts
    finished Sessions is beaten by abandoning them.

    So exactly two cases release. Nothing checkpointed at all: the run died before the graph wrote a
    thing (an invalid payload, a store that would not build, a quota that died on the Diagnostic) and
    the Candidate has already been told to start a new Session, not to resume this one. COMPLETE: the
    interview is over, and a question the Supervisor ended early on is never going to be asked.
    """
    if reservation is None:
        return
    identity, reserved = reservation
    try:
        values = _checkpoint_values(api_state, runtime.session_id)
        if not values:
            unused = reserved
        elif str(values.get("status", "")) == SessionStatus.COMPLETE.value:
            unused = reserved - int(values.get("question_count", 0))
        else:
            return  # resumable: the reservation is still owed to this Session
        if unused > 0:
            record_questions_released(identity, unused, session=runtime.session_id)
    except Exception:  # noqa: BLE001 - a refund must never mask the run's own outcome, or wedge the id
        logger.warning("could not release the question reservation for %r", runtime.session_id, exc_info=True)


def _unknown_session_message(session_id: str) -> str:
    """The web's half of the CLI's unknown-``--resume``-id refusal, in the same opening words (0019).

    Deliberately NOT the CLI string verbatim: ``--session-id`` is meaningless in a browser, and the
    CLI's hint lists every thread_id in the checkpoint DB plus the DB's path — one Candidate's socket
    must never be handed the ids of everyone else's Sessions.
    """
    return (
        f"No saved Session found for {session_id!r}. It was never started here, or its checkpoint "
        "has expired. Start a new Session from Setup — there is nothing to resume."
    )


def _checkpoint_values(api_state: WebApiState, session_id: str) -> Mapping[str, Any]:
    """A resumed Session's stored state, read BEFORE the graph is built.

    A resume payload carries only a mode, so everything the driver must know up front —
    ``language_mode`` for the embedder, ``max_questions`` for the budget rail — comes from here.
    Returns ``{}`` on any read failure: a missing checkpoint is the "unknown session" path, which
    the graph reports far better than a crash in here would.
    """
    try:
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer:
            checkpoint = checkpointer.get(cast("Any", session_config(session_id)))
        raw: Mapping[str, Any] = cast("Mapping[str, Any]", checkpoint or {})
        return cast("Mapping[str, Any]", raw.get("channel_values") or {})
    except Exception:
        logger.warning("could not read the checkpoint for resumed Session %r", session_id, exc_info=True)
        return {}


def _session_language_mode(
    payload: StartSessionPayload | ResumeSessionPayload,
    resume: bool,
    checkpoint_values: Mapping[str, Any],
) -> str:
    """The Session's language mode, known BEFORE the graph is built (R-14).

    A fresh Session carries it on the start payload. A *resumed* one does not, so it has to come out
    of the checkpoint, or resuming a Vietnamese Session would silently rebuild its retrieval on the
    English embedder and rank near-randomly for the rest of the interview.
    """
    if not resume:
        return getattr(payload, "language_mode", DEFAULT_LANGUAGE_MODE)
    return str(checkpoint_values.get("language_mode") or DEFAULT_LANGUAGE_MODE)


def _persist_export(api_state: WebApiState, session_id: str, final_state: dict[str, Any]) -> None:
    """Write the completed Session's Markdown to disk so a restart cannot eat the report.

    Best-effort on purpose: the Candidate has just finished an interview, and a full disk or a
    read-only mount must not turn a completed Session into an error event. The in-memory copy still
    serves this process, and the failure is logged rather than raised.
    """
    try:
        export_session_markdown(final_state, export_path(api_state.exports_dir, session_id))
    except OSError:
        logger.exception("could not persist the Markdown export for Session %r", session_id)


def _stream_graph(
    graph,
    initial_state: Mapping[str, Any] | None,
    config: dict[str, Any],
    runtime: RuntimeSession,
    *,
    budget_stop: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> dict:
    """Drive the graph, converting the two out-of-band stop conditions into typed signals.

    The budget rail sits next to the cancel check on purpose (R-25): raised HERE, outside the graph,
    it can never reach ``question_node``'s ``except Exception`` net and be recorded as a
    zero-evidence ``failed`` question — the corruption ADR 0005 forbids. It is the same shape as the
    cancel path rather than a fourth degrade path.
    """
    final_state: dict[str, Any] | None = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        if runtime.cancelled.is_set():
            raise CandidateInputUnavailable("Session was cancelled.")
        final_state = dict(event)
        runtime.emit({"type": "state_update", "state": final_state})
        # Checked AFTER the state goes out, exactly as the CLI prints the live update first: the
        # question the Candidate just resolved IS in the checkpoint, and a suspend that arrives with
        # no state carrying it looks to the UI like a crash that ate the last answer.
        if budget_stop is not None and (reason := budget_stop(final_state)):
            raise SessionBudgetSuspended(reason)
    if final_state is None:
        raise RuntimeError("Session graph produced no final state")
    return final_state
