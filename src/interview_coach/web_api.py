"""FastAPI/WebSocket surface for the local React MVP."""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field, ValidationError
from starlette.status import WS_1008_POLICY_VIOLATION

from .concepts import build_concept_store
from .config import Settings, load_settings
from .demo_llm import DemoLLMClient
from .diagnostic import CandidateProfile, diagnose_or_degrade
from .exporter import export_session_markdown, render_session_markdown
from .ledger import load_priors, save_posteriors
from .llm import LLMClient, build_client, build_role_clients
from .microloop import CandidateInputUnavailable, CandidateIntent
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

logger = logging.getLogger(__name__)

SessionMode = Literal["auto", "demo", "live"]


class StartSessionPayload(BaseModel):
    type: Literal["start_session"]
    mode: SessionMode = "auto"
    target_role: str = "machine learning engineer"
    target_companies: list[str] = Field(default_factory=list)
    claimed_skills: dict[str, float] = Field(default_factory=dict)
    candidate_id: str = ""  # cross-session Skill ledger id (0023); empty = one-shot cold start
    max_questions: int = Field(DEFAULT_MAX_QUESTIONS, ge=1, le=10)
    max_elapsed_seconds: float = Field(DEFAULT_MAX_ELAPSED_SECONDS, gt=0)
    language_mode: Literal["en", "vn", "mixed"] = "en"  # issue 0024, ADR 0007


class ResumeSessionPayload(BaseModel):
    type: Literal["resume_session"]
    mode: SessionMode = "auto"


class CandidateAnswerPayload(BaseModel):
    type: Literal["candidate_answer"]
    answer: str


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


@dataclass
class RuntimeSession:
    session_id: str
    mode: str
    emit: EventEmitter
    answers: queue.Queue[Any] = field(default_factory=queue.Queue)
    cancelled: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def reset_run_state(self) -> None:
        # A single socket can run start -> cancel -> start again. Without a fresh queue and event the
        # second run inherits a permanently-set cancelled flag (aborts instantly) and a stale sentinel
        # left in the queue (consumed as the first answer). Reset before each run.
        self.answers = queue.Queue()
        self.cancelled = threading.Event()

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


def configure_session_logging() -> None:
    """Make the per-call ``llm-call`` trace visible in whichever process actually serves requests.

    Uvicorn configures logging in the **worker**, and under ``--reload`` that worker is a freshly
    spawned process where the CLI's own ``basicConfig`` never ran. Uvicorn attaches handlers to its
    own loggers only, so ``interview_coach`` records reach a bare root logger and die at WARNING —
    silently, and only in reload mode, which makes the trace look flaky rather than unconfigured.
    R-26's trace is how a silent judge failover is caught after the fact (ADR 0009 addendum a), so
    it has to survive every way this app gets started. Module import is the one hook that runs in
    the serving process either way.
    """
    log = logging.getLogger("interview_coach")
    log.setLevel(logging.INFO)
    # Only self-configure when nothing else will emit these records; the CLI's basicConfig installs
    # a root handler, and adding a second one here would print every line twice.
    if not log.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)


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
        # Defined behavior for two tabs on one session_id: reject the second so two graphs can't run
        # concurrently against one checkpoint thread. One live socket per Session id.
        if session_id in api_state.runtimes:
            await websocket.send_json(
                {"type": "session_error", "error": "This Session id already has an active connection."}
            )
            await websocket.close()
            return
        outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        emit = EventEmitter(asyncio.get_running_loop(), outgoing)
        runtime = RuntimeSession(session_id=session_id, mode="pending", emit=emit)
        sender = asyncio.create_task(_send_events(websocket, outgoing))
        api_state.runtimes[session_id] = runtime
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
                    runtime.answers.put(payload.answer)
                else:
                    # Cancel is a control signal (ADR 0005): flag it and drop the sentinel so a blocked
                    # QueueCandidate.answer() raises CandidateIntent. _run_session_thread emits the
                    # terminal event; no "" is injected as a fake answer.
                    runtime.cancelled.set()
                    runtime.answers.put(_CANCEL)
        except WebSocketDisconnect:
            runtime.cancelled.set()
            runtime.answers.put(_CANCEL)
        finally:
            sender.cancel()
            # Only drop the map entry if it is still ours — a rejected second connection must not evict
            # the live one, and a stale run must not evict a newer registration.
            if api_state.runtimes.get(session_id) is runtime:
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


configure_session_logging()
app = create_app()


async def _send_events(websocket: WebSocket, outgoing: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        event = await outgoing.get()
        await websocket.send_json(event)


def _parse_payload(raw: dict[str, Any]) -> ClientPayload:
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
    try:
        client = _client_for_mode(runtime.mode, api_state.settings)
        # ADR 0010: demo mode's client is not a router, so the bundle collapses to single-client
        # semantics; live mode pins the judge and applies any ROLE_* overrides.
        roles = build_role_clients(api_state.settings, client)
        concept_store = build_concept_store("memory", seed=True)
        resource_store = build_resource_store("memory", seed=True)
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer:
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
                profile = CandidateProfile(
                    target_role=payload.target_role,
                    target_companies=tuple(payload.target_companies),
                    claimed_skills=payload.claimed_skills,
                )
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
            final_state = _stream_graph(graph, initial_state, config, runtime)
        if final_state is not None:
            api_state.completed_sessions[runtime.session_id] = final_state
            # Persist posteriors for a returning Candidate (0023); candidate_id rides in the state so a
            # resumed Session saves too. save_posteriors no-ops on an empty id.
            if final_state.get("status") == SessionStatus.COMPLETE.value:
                _persist_export(api_state, runtime.session_id, final_state)
                save_posteriors(
                    api_state.ledger_db,
                    str(final_state.get("candidate_id", "")),
                    skill_states_from_state(final_state),
                    now=time.time(),
                )
            runtime.emit({"type": "session_completed", "state": final_state})
    except CandidateIntent as err:
        # ADR 0005 / issue 0017: the Candidate asked to stop (web cancel/disconnect). This is intent,
        # not an infrastructure failure — a distinct control-flow branch. The supervisor re-raises it
        # past the per-question failure-isolation net, so the in-flight question is never recorded as a
        # zero-evidence `failed` and the checkpoint stays resumable. Report it, don't score anything.
        logger.info("Session %s cancelled by Candidate intent: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session cancelled: {err}"})
    except Exception as err:  # noqa: BLE001 - API boundary converts graph/provider failures to events
        logger.exception("Session %s failed", runtime.session_id)
        runtime.emit({"type": "session_error", "error": f"{type(err).__name__}: {err}"})


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
            logger.warning("could not prune checkpoint thread %s", thread_id, exc_info=True)
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


def _persist_export(api_state: WebApiState, session_id: str, final_state: dict[str, Any]) -> None:
    """Write the completed Session's Markdown to disk so a restart cannot eat the report.

    Best-effort on purpose: the Candidate has just finished an interview, and a full disk or a
    read-only mount must not turn a completed Session into an error event. The in-memory copy still
    serves this process, and the failure is logged rather than raised.
    """
    try:
        export_session_markdown(final_state, export_path(api_state.exports_dir, session_id))
    except OSError:
        logger.exception("could not persist the Markdown export for Session %s", session_id)


def _stream_graph(
    graph, initial_state: Mapping[str, Any] | None, config: dict[str, Any], runtime: RuntimeSession
) -> dict:
    final_state: dict[str, Any] | None = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        if runtime.cancelled.is_set():
            raise CandidateInputUnavailable("Session was cancelled.")
        final_state = dict(event)
        runtime.emit({"type": "state_update", "state": final_state})
    if final_state is None:
        raise RuntimeError("Session graph produced no final state")
    return final_state
