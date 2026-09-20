"""Process-level concerns with no request in scope: worker count, logging, checkpoint hygiene.

Split out of ``web_api`` under GH #124. One reason to change: how the server process is configured
or swept, which is nothing to do with what any socket is doing. Every function here runs at import,
at startup, or from the CLI — never inside a route.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from .config import Settings
from .web_runtime import WebApiState

logger = logging.getLogger(__name__)


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


def prune_checkpoints(checkpointer: Any, *, max_age_seconds: float, now: float, db_label: str = "") -> list[str]:
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
    pruned: list[str] = []
    for thread_id, stamp in sorted(newest.items()):
        if now - stamp <= max_age_seconds:
            continue
        try:
            checkpointer.delete_thread(thread_id)
        except sqlite3.DatabaseError as err:
            # Not this thread's problem — the FILE is damaged, and every remaining delete would raise
            # the same thing. Said once, in the words an operator can act on: the per-thread warning
            # below reads like a transient hiccup, and a checkpoint DB that cannot be written is also
            # one that cannot resume a Session, which is the failure this server is least able to
            # explain afterwards. Measured on this repo's own dev checkpoint file: `PRAGMA
            # integrity_check` reported "wrong # of entries in index sqlite_autoindex_writes_1" and
            # startup printed one full traceback per stale thread, none of them saying "corrupt".
            logger.error(
                "the checkpoint database at %s is damaged (%s: %s); the sweep stopped and RESUME IS "
                "NOT RELIABLE until it is repaired. Check it with `PRAGMA integrity_check`, repair "
                "with `REINDEX`, or stop the server and delete the file to start clean — deleting it "
                "abandons every in-flight Session, completed ones are already in the exports.",
                db_label or "the configured COACH_CHECKPOINT_DB",
                type(err).__name__,
                err,
            )
            return pruned
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


def _sweep_checkpoints_at_startup(api_state: WebApiState) -> None:
    """Reap stale checkpoint threads once, at app construction — the DB had no reaper at all."""
    ttl = api_state.settings.checkpoint_ttl_seconds
    if ttl <= 0:
        return
    try:
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer:
            prune_checkpoints(checkpointer, max_age_seconds=ttl, now=time.time(), db_label=str(api_state.checkpoint_db))
    except Exception:
        # A cleanup must never be the reason the server fails to start.
        logger.warning("checkpoint sweep failed at startup", exc_info=True)
