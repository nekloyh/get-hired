"""FastAPI/WebSocket surface for the local React MVP."""

from __future__ import annotations

import asyncio
import logging
import os
import queue
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.status import WS_1008_POLICY_VIOLATION

from .concepts import (
    resolve_concept_store_kind,
)
from .config import Settings, load_settings
from .exporter import render_session_markdown
from .supervisor import (
    SessionStatus,
)
from .web_ops import (
    _sweep_checkpoints_at_startup,
    _validate_auth_settings,
    configure_session_logging,
    guard_single_worker,
)
from .web_protocol import (
    DEFAULT_ALLOWED_ORIGINS,
    AuthPayload,
    CandidateAnswerPayload,
    ResumeSessionPayload,
    StartSessionPayload,
    _frame_refused,
    _parse_payload,
    allowed_origins,
    authenticate_socket,
    origin_allowed,
    receive_json_frame,
    token_matches,
)
from .web_runtime import (
    EventEmitter,
    RuntimeSession,
    WebApiState,
    _claim_session_id,
    export_path,
)
from .web_session_driver import (
    _checkpoint_values,
    _is_running,
    _run_session_thread,
    _select_mode,
)

logger = logging.getLogger(__name__)


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

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # wait=False: a shutdown must not block uvicorn for the length of a 120s join.
        api_state.join_pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Adaptive Interview Coach API", lifespan=_lifespan)
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
            "COACH_ALLOWED_ORIGINS to the exact origin serving the app (`*` is refused).",
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
                    emit(_frame_refused(str(err)))
                    continue
                if isinstance(payload, StartSessionPayload):
                    if _is_running(runtime):
                        emit(_frame_refused("A Session is already running on this socket."))
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
                        emit(_frame_refused("A Session is already running on this socket."))
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
                    # NEW-01 / ADR 0005: an answer is evidence about ONE turn, and the server decides
                    # which. Without this the queue is a bare FIFO, so a second answer sent while one
                    # question is pending shifts every later question's evidence onto the wrong
                    # prompt — silently, with no error, all the way into the Skill ledger.
                    # The id is REQUIRED, not merely checked when present. "Nothing is pending" is
                    # not a state a client can rely on: this loop and the graph thread run
                    # concurrently, so an id-less answer that arrives just after the NEXT question is
                    # armed matches it and is scored against the wrong question — measured at about
                    # one run in eight. The server mints an id for every question it asks, so an
                    # answer naming none cannot be bound to anything.
                    expected = runtime.awaiting_turn_id
                    if expected is None or payload.turn_id != expected:
                        emit(_frame_refused("Answer refused: it does not answer the pending question."))
                        continue
                    try:
                        runtime.answers.put_nowait(payload.answer)
                    except queue.Full:
                        emit(_frame_refused("Answer dropped: earlier answers are still being processed."))
                    else:
                        runtime.awaiting_turn_id = None
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
            text = stored.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.strip():
            return text
        # Nothing readable on disk: the write failed (`_persist_export` logs and swallows), or a
        # pre-atomic-publish build left a torn file — atomicity only prevents NEW tears. The
        # checkpoint still holds the finished state, and rendering it costs one SQLite read on a path
        # that was about to 404 anyway. The COMPLETE guard is load-bearing: without it a cancelled or
        # in-flight Session's checkpoint would be served as a finished report (ADR 0005 — a run that
        # never finished must not be presented as evidence).
        values = _checkpoint_values(api_state, session_id)
        if str(values.get("status", "")) == SessionStatus.COMPLETE.value:
            logger.warning(
                "serving Session %r's export from its checkpoint: %s is missing or empty", session_id, stored
            )
            return render_session_markdown(values)
        raise HTTPException(status_code=404, detail="No completed Session found for this Session id.")

    _sweep_checkpoints_at_startup(api_state)
    # Registered last, deliberately: a mount at "/" matches everything, so every API route above has
    # to be in the table already or the UI would swallow them.
    _mount_static_ui(app, static_dir if static_dir is not None else resolved.static_dir)
    return app


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
