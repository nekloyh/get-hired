"""Per-Session counters for structural-noise and transport events (free-tier hardening).

The judge's structural-noise folds (the Evaluation sanitizer), structured-output retries, and
transport backoffs were previously visible only as scattered log lines, so a NEW noise mode from
the live model first showed up as a red bench with no warning (the 24/29 day). These counters make
noise drift measurable: the bench snapshots them around a run and prints the delta, so a new fold
pattern surfaces as a counter moving while the run is still green.

Deliberately minimal: one Counter behind four functions — but per-Session, not per-process. The web
API runs one daemon thread per Session, so a process-wide Counter let one Candidate's sanitizer fold
land inside another Candidate's judge-call window, where ``evaluator._noise_events`` read it as THIS
judgment's noise and haircut a clean confidence: one Candidate's provider hiccup altering another
Candidate's scored evidence, which ADR 0005 forbids. ``session_counters()`` swaps in a fresh Counter
for the current context and ``usage.session_scope`` enters it, so both Session drivers (CLI and web
API) get isolation without threading a parameter through every call site. Outside a Session — bench
and forge, which snapshot it around a run for the ADR 0009 report — the module-level Counter is
untouched, so those reports read as before.
Not persisted — persistence belongs to the usage ledger (usage.py), which tracks spend, not noise.
"""

from __future__ import annotations

import functools
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_counters: Counter[str] = Counter()
# The Session's own counters, when one is in scope. A ContextVar for the same reason usage.py's
# _SESSION_ID is one: incr() is called from deep inside the provider clients and from inside a
# pydantic validator classmethod that has no reference to the call at all, so attribution can only be
# ambient. langgraph runs sync nodes in a COPIED context — a copy shares the Counter OBJECT, so every
# node mutates the Counter its driver installed. A thread started with threading.Thread starts from
# an EMPTY context, which is why the scope is entered inside the thread, not around it.
_session_counters: ContextVar[Counter[str] | None] = ContextVar("interview_coach_telemetry_session", default=None)


def _active() -> Counter[str]:
    scoped = _session_counters.get()
    return _counters if scoped is None else scoped


@contextmanager
def session_counters() -> Iterator[None]:
    """Route counter writes inside this block to a fresh Counter owned by this Session."""
    token = _session_counters.set(Counter())
    try:
        yield
    finally:
        _session_counters.reset(token)


def incr(key: str, n: int = 1) -> None:
    """Count ``n`` occurrences of a named event (e.g. ``'sanitizer.judgment_flattened'``)."""
    _active()[key] += n


def snapshot() -> dict[str, int]:
    """The current counts as a plain dict — safe to hold and diff against a later snapshot."""
    return dict(_active())


def reset() -> None:
    _active().clear()


def delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    """Counts that moved between two snapshots — what one bench/forge run actually folded."""
    return {key: count - before.get(key, 0) for key, count in after.items() if count != before.get(key, 0)}


# --- Call attribution (#144) ------------------------------------------------------------------------
# Every `llm-call` trace line (llm._OpenAICompatibleClient._trace_call) carries the Session (from
# usage.session_scope) and these fields, so a live Session's trajectory can be rebuilt from its log
# alone: which question, which turn, which role. Ambient for the reasons the counters above are:
# the line is written deep inside the provider client, which knows none of this. langgraph's copied
# node context and a Session's own thread both preserve it, exactly as they preserve the counters.
_trace: ContextVar[tuple[tuple[str, str], ...]] = ContextVar("interview_coach_trace", default=())


@contextmanager
def trace_scope(**fields: object) -> Iterator[None]:
    """Stamp ``fields`` (``question=``, ``turn=``, ``role=``) on every ``llm-call`` line inside this block.

    Nested scopes add to what the outer one set and may override it; a ``None`` value is ignored.
    """
    merged = dict(_trace.get())
    merged.update({key: str(value) for key, value in fields.items() if value is not None})
    token = _trace.set(tuple(merged.items()))
    try:
        yield
    finally:
        _trace.reset(token)


def trace_fields() -> dict[str, str]:
    """The attribution in scope right now, as a plain dict."""
    return dict(_trace.get())


def traced_role(role: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Mark an agent's entry point: every provider call made inside it is traced as ``role``.

    Set at the entry point rather than at each call site, because the function IS that role: every
    call ``evaluate`` makes is a judge call, including the Panel's, whichever client object carries it.
    """

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def traced(*args: P.args, **kwargs: P.kwargs) -> R:
            with trace_scope(role=role):
                return fn(*args, **kwargs)

        return traced

    return decorate
