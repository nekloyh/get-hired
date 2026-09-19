"""Per-socket Session runtime: the Candidate bridge, the registry, and who owns a Session id.

Split out of ``web_api`` under GH #124. One reason to change: how a live Session is represented in
memory and how two sockets contend for the same id. Nothing here knows about FastAPI routes, and
nothing here knows about LangGraph — the graph driver is ``web_session_driver``.

Everything is re-exported from ``web_api`` so the public import path is unchanged. Note for tests:
monkeypatching a CONSTANT (``STALE_RUNTIME_JOIN_SECONDS``) has to target this module, because the
code that reads it lives here now; classes and functions can still be reached either way.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import Settings
from .microloop import CandidateInputUnavailable

logger = logging.getLogger(__name__)

# Input bounds (AUDIT §3.1): one client must not be able to grow memory without limit.
ANSWER_QUEUE_MAXSIZE = 8

# How long a reconnect waits for the previous run's thread to leave an in-flight provider call. Covers
# one timed-out call plus a retry (LLM_TIMEOUT_SECONDS 60 x 2); a full 4-attempt retry storm can run
# ~4 minutes, in which case the client is told to retry rather than the wait growing to match.
STALE_RUNTIME_JOIN_SECONDS = 120.0

# NEW-03. That join blocks a whole thread, so it gets its own bounded pool: on the loop's default
# executor (min(32, cpu+4)) a mass reconnect — an nginx restart, a cohort resuming after sleep —
# pins every thread the loop shares with `getaddrinfo` and every other `run_in_executor(None, ...)`,
# and the NEXT reconnect queues inside the executor, so its socket sits silent for the length of
# someone else's join instead of being refused. "One waiter per id" bounds waiters per id, not
# globally, which is why the pool is paired with a global cap of the same size: with max_workers ==
# the cap an admitted join always gets a thread, and a refused one never waits for one.
MAX_CONCURRENT_STALE_JOINS = 8

# Every Session runs on a thread named `session-<id>`. The name is load-bearing twice over: a
# `faulthandler` dump or `py-spy dump` on a wedged deployment names the Session that is stuck
# instead of `Thread-7`, and the suite's teardown (tests/conftest.py) uses the prefix to prove no
# Session thread outlived the test that started it (GH #134).
SESSION_THREAD_NAME_PREFIX = "session-"

# Completed states kept in RAM; the export endpoint falls back to the Markdown `_persist_export` wrote.
MAX_COMPLETED_SESSIONS_IN_MEMORY = 64

# Completed-Session Markdown outlives the process here (R-08). The in-memory dict alone meant a
# restart ate every report that had not been downloaded yet, while the Session itself sat safely in
# the checkpoint DB — the one artifact the Candidate actually keeps was the one thing not persisted.
DEFAULT_EXPORTS_DIR = "data/exports"

# A Session id that is safe to use as a filename verbatim. Anything else gets digested (see
# ``export_path``) rather than rejected, so an unusual id still produces a report.
SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


_CANCEL: Any = object()


class QueueCandidate:
    """Candidate bridge: graph thread emits a question, then waits for browser input."""

    def __init__(
        self,
        emit: EventEmitter,
        answers: queue.Queue[Any],
        cancelled: threading.Event,
        begin_turn: Callable[[], int],
    ) -> None:
        self._emit = emit
        self._answers = answers
        self._cancelled = cancelled
        self._begin_turn = begin_turn

    def answer(self, question: str) -> str:
        # Arm the binding BEFORE the frame leaves: the client cannot answer a question it has not
        # received, so set-then-emit is what makes "an answer arrived with nothing pending" mean
        # exactly that, with no window in which a legitimate answer would be refused.
        self._emit({"type": "question", "question": question, "turn_id": self._begin_turn()})
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
    # NEW-01. `turn_seq` counts up for the life of the socket and is deliberately NOT reset per run:
    # restarting it would let an answer still in flight from a cancelled run match a turn of the run
    # that replaced it. `awaiting_turn_id` is the one turn the graph thread is blocked on; None means
    # nothing is pending, and every answer that arrives then is refused rather than buffered.
    turn_seq: int = 0
    awaiting_turn_id: int | None = None

    def begin_turn(self) -> int:
        self.turn_seq += 1
        self.awaiting_turn_id = self.turn_seq
        return self.turn_seq

    def reset_run_state(self) -> None:
        # A single socket can run start -> cancel -> start again. Without a fresh queue and event the
        # second run inherits a permanently-set cancelled flag (aborts instantly) and a stale sentinel
        # left in the queue (consumed as the first answer). Reset before each run.
        self.answers = _bounded_answers()
        self.cancelled = threading.Event()
        self.run_finished = False
        self.awaiting_turn_id = None

    @property
    def run_in_flight(self) -> bool:
        return self.thread is not None and not self.run_finished

    def cancel(self) -> None:
        # A cancel supersedes queued answers: drain so the sentinel can never be lost to a full queue.
        self.cancelled.set()
        self.awaiting_turn_id = None  # a cancel closes the turn; a late answer is not evidence
        with suppress(queue.Empty):
            while True:
                self.answers.get_nowait()
        self.answers.put_nowait(_CANCEL)

    def start(self, target, *args: Any) -> None:
        self.thread = threading.Thread(
            target=target, args=args, daemon=True, name=f"{SESSION_THREAD_NAME_PREFIX}{self.session_id}"
        )
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
    # NEW-03: stale-run joins run here, never on the loop's shared default executor. Threads are
    # spawned on demand, so an app that never sees a reconnect never pays for one.
    join_pool: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_STALE_JOINS, thread_name_prefix="stale-join"
        )
    )
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


_ACTIVE_ELSEWHERE = "This Session id already has an active connection."
_STILL_FINISHING = "The previous run of this Session is still finishing; retry in a moment."
_TOO_MANY_JOINS = "The server is already waiting on the maximum number of previous runs; retry in a moment."
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
        if len(api_state.waiting) >= MAX_CONCURRENT_STALE_JOINS:
            # NEW-03: per-id is not a global bound. Past the cap a reconnect is refused IMMEDIATELY,
            # because the alternative is not a slower answer but no answer at all: the claim would
            # queue inside the pool and the socket would stay silent for someone else's join.
            logger.warning(
                "refusing a reconnect for %r: %d stale-run joins already in flight",
                session_id,
                len(api_state.waiting),
            )
            return _TOO_MANY_JOINS
        api_state.waiting.add(session_id)
    try:
        if stale.thread is not None and stale.thread.is_alive():
            # Closed socket, thread still winding down: cancellation is already signalled, so the only
            # long wait is an in-flight provider call.
            await asyncio.get_running_loop().run_in_executor(
                api_state.join_pool, stale.thread.join, STALE_RUNTIME_JOIN_SECONDS
            )
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
