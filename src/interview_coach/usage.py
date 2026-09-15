"""Client-side daily token ledger — the only workable free-tier budget rail.

The OpenAI free daily allowance for gpt-5.4-mini (2.5M tokens/day) is NOT exposed by the API:
rate-limit headers carry only the per-minute window (200k TPM / 500 RPM, probed 2026-07-11), so
what remains of the day's budget can only be known by counting what we spent. Every provider call
appends one JSONL line here (from the response's ``usage`` field); the bench and forge print the
day's spend so a long run is never started blind into a dead quota.

R-25 adds the rails a *product* needs on top of the day counter: a **per-run** token budget (nothing
bounded a single Session before — a retry storm could eat the whole day) and a questions/day cap per
token identity. The Session-behaviour half of those rails is ADR 0005's third category, **budget
exhaustion → suspend-and-resume**, and it deliberately lives in the Session drivers rather than in
the graph: a stop raised outside ``question_node`` can never be caught by its ``except Exception``
net and turned into a zero-evidence ``failed`` question, which is precisely the fake-evidence
corruption that ADR forbids.

Append-only JSONL under ``logs/`` (already gitignored runtime state), tolerant of malformed lines.
Rows come in four kinds and every reader identifies its own by a marker, never by "which keys happen
to be present":

* token rows      — ``prompt_tokens``/``completion_tokens``, optionally attributed to a ``session``
* ``session_run`` — one run's starting baseline, so the per-run rail can measure a delta
* ``questions``   — a product-cap reservation against a token identity
* ``quota_exhausted`` / ``quota_retry`` — the provider's terminal ``insufficient_quota``, latched

M0a / F1 corrects the half of that sentence that was wrong. Recording still must never take down
the call *in flight* — a crashed judgment is worse than a late ledger line — but a lost ledger line
is **not** noise: it is spend nobody can see, and the day counter that every rail above reads then
silently under-counts. So a failed write no longer returns quietly. It latches an **accounting
fault**, and while one is unresolved every metered call is refused. Two conditions, deliberately
distinguished, because their honest remedies differ:

* **before any call** — the ledger path is unwritable (:func:`check_ledger_writable`). Nothing has
  been spent unaccounted; fixing the path clears it with no bookkeeping to repair.
* **after a billed call** — the provider answered, we were charged, and the token row would not
  write (:func:`record_usage`). The day's spend is now *undetermined*, which is not the same as
  zero. The unwritten row is parked in a sidecar next to the ledger and the condition stays
  **unreconciled** until ``coach usage --reconcile`` replays it, so the tokens are folded back in
  rather than forgiven.

Days are UTC, matching the provider's daily reset.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from . import telemetry
from .filelock import locked

logger = logging.getLogger(__name__)

# Anchored to the repo root (the same parent-hop pattern bench._default_cases_path uses), NOT the
# CWD: a CWD-relative ledger fragments per launch directory, and a fragmented ledger under-counts
# the day's spend — silently defeating the pre-run budget check it exists to feed.
DEFAULT_LEDGER_PATH = (Path(__file__).parent / ".." / ".." / "logs" / "usage-ledger.jsonl").resolve()


def utc_date() -> str:
    """Today's UTC day key — the one convention shared by the ledger, the bench, and the daily reset."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


# gpt-5.4-mini's free daily allowance. A soft rail: crossing it does not block calls (the provider
# 429s with insufficient_quota on its own) — it exists so callers can refuse to START a run that
# clearly cannot fit in what is left of the day.
DEFAULT_DAILY_TOKEN_BUDGET = 2_500_000


def ledger_path() -> Path:
    return Path(os.environ.get("COACH_USAGE_LEDGER", str(DEFAULT_LEDGER_PATH)))


# The unwritten rows live beside the ledger they could not join, under the ledger's own name plus
# this suffix — so an operator who knows where the ledger is already knows where the fault is, and a
# `docker cp` or a volume backup of the state directory carries both or neither.
LEDGER_FAULT_SUFFIX = ".unreconciled"


def ledger_fault_path(path: Path | None = None) -> Path:
    """Where an accounting fault parks the rows the ledger refused."""
    target = path or ledger_path()
    return target.with_name(target.name + LEDGER_FAULT_SUFFIX)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        logger.warning("%s=%r is not an integer; using default %d", name, raw, default)
        return default


def daily_token_budget() -> int:
    return _env_int("LLM_DAILY_TOKEN_BUDGET", DEFAULT_DAILY_TOKEN_BUDGET)


# --- measured facts, re-derived from logs/usage-ledger.jsonl (1,431 rows on main @184f5a2) -------
#
# The ledger is gitignored runtime state, so no test can re-read it; what a test CAN pin is that
# every number below it derives still follows from it, which is what test_usage.py does. To re-take
# the measurements themselves, gap-cluster (>10 min) the openai/gpt-5.4-mini rows and read off the
# clusters carrying the `coach session` signature — a ~450p/240c Diagnostic, then repeating
# evaluator/interviewer triples, then a ~1,800p planner call — as opposed to the bench sweeps:
#   2026-07-11T13:21  16 calls  26,866 tok  (1,679/call — the heaviest Session measured)
#   2026-07-27T05:12   4 calls   5,596 tok  (1,399/call)
#   2026-07-27T07:36  11 calls  14,616 tok  (1,329/call)
#   2026-07-27T12:21   5 calls   6,836 tok  (1,367/call)
#   2026-07-27T12:42  17 calls  21,891 tok  (1,288/call — 1 Diagnostic + 5x3 + 1 planner)
# The two bench sweeps are the largest *sustained* per-call means on record: 1,720/call over 455
# calls and 1,956/call over 778.

HEAVIEST_MEASURED_SESSION_TOKENS = 26_866
# The single largest provider call in the whole ledger. This — not any mean — is the per-call figure
# a CEILING must use: a runaway is precisely the case where the expensive call is the one that
# repeats, so a rail sized on the average fires on a legitimate Session made of big prompts.
LARGEST_MEASURED_CALL_TOKENS = 2_663
# The opening call of each Session-shaped cluster — the Diagnostic — measured 681, 692, 694 and 993.
# One runs per Session, so the estimate carries the largest.
HEAVIEST_MEASURED_DIAGNOSTIC_TOKENS = 993

# Everything below is DERIVED from the three measurements above, rounded up to the next 100 so the
# numbers read as estimates rather than as false precision. test_usage.py re-does each division, so
# a hand-nudged constant reddens instead of quietly re-sizing a rail.
MEASUREMENT_ROUNDING = 100
WORST_CASE_TOKENS_PER_CALL = 2_700  # ceil(2,663 / 100) * 100
SESSION_SETUP_TOKENS = 1_000  # ceil(993 / 100) * 100
SESSION_TOKENS_PER_QUESTION = 5_200  # ceil((26,866 - 993) / 5 / 100) * 100

# The daily allowance restated in product units: 2,500,000 / 5,200. Deliberately NOT a small
# per-user number — with one shared secret (R-07) the identity bucket IS the whole deployment, so a
# 10/day default would cap it at two Sessions. The env var is the real product control; this default
# is a backstop that cannot break a shared-token deployment.
DEFAULT_DAILY_QUESTION_CAP = 480


# --- how many provider calls a Session can possibly make ----------------------------------------
#
# Restated here rather than imported: every module that owns one of these numbers (evaluator,
# interviewer, microloop, supervisor) imports the provider clients, which import THIS module, so an
# import would be circular. tests/test_usage.py::test_the_call_model_matches_the_constants_it_restates
# reads the real ones and fails the moment a restatement drifts.
#
# Every number below counts PROVIDER calls, and a schema retry is a provider call: chat_json feeds
# the validation error back and asks again, and that second ask is an HTTP success that records
# tokens. Transport retries (llm._TRANSPORT_ATTEMPTS) are deliberately NOT counted — they only fire
# when the call never completed, so nothing was billed and nothing was recorded.

STRUCTURED_ATTEMPTS = 2  # 1 + LLMClient.chat_json's default max_retries
JUDGE_ATTEMPTS = 3  # 1 + evaluator.JUDGE_MAX_RETRIES
NATIVE_TOOL_ATTEMPTS = 2  # interviewer._NATIVE_TOOL_ATTEMPTS
PANEL_ESCALATIONS_PER_QUESTION = 1  # evaluator.PanelBudget.per_question() default

# One judgment, plus the evidence-degrade re-pass evaluator._evaluate_once makes when the verbatim
# citation check survives its retries.
EVALUATION_CALLS = 2 * JUDGE_ATTEMPTS
# A committee is a Skeptic, an Advocate, and a full re-judgment that reads both.
PANEL_CALLS = 2 * STRUCTURED_ATTEMPTS + EVALUATION_CALLS
# Each tool round-trip is the forced lookup_concept request plus the structured final answer.
FOLLOW_UP_CALLS = NATIVE_TOOL_ATTEMPTS * (1 + STRUCTURED_ATTEMPTS)
SEED_RENDER_CALLS = STRUCTURED_ATTEMPTS  # vn/mixed only; `en` passes through with no call
SUPERVISOR_CALLS = STRUCTURED_ATTEMPTS
DIAGNOSTIC_CALLS = STRUCTURED_ATTEMPTS
STUDY_PLAN_CALLS = STRUCTURED_ATTEMPTS


# One logical call through LLMRouter can bill TWO providers: the primary's token row is written
# inside `_create()` and only THEN does an empty completion raise EmptyCompletionError, which
# `is_provider_failure()` treats as an outage — so the fallback is asked, and billed, for the same
# request. Two, never three: the router resolves exactly one fallback and its fallback call is
# terminal. The judge is excluded deliberately — `build_role_clients` always seats it on a pinned
# provider client (ADR 0009 addendum a), so it cannot fail over, and doubling its calls would loosen
# the runaway ceiling by ~44% for a case that cannot happen.
FAILOVER_PROVIDERS_PER_CALL = 2


def worst_case_question_calls(max_turns: int) -> int:
    """Provider calls one question can cost with every retry, degrade, escalation and failover."""
    turns = max(1, max_turns)
    routed = (
        SEED_RENDER_CALLS
        # The last turn hits the safety cap, so it never asks for a follow-up.
        + (turns - 1) * FOLLOW_UP_CALLS
        + SUPERVISOR_CALLS
    )
    pinned = turns * EVALUATION_CALLS + PANEL_ESCALATIONS_PER_QUESTION * PANEL_CALLS
    return FAILOVER_PROVIDERS_PER_CALL * routed + pinned


def worst_case_session_calls(max_questions: int, max_turns: int) -> int:
    """Provider calls a Session can cost given the hard rails it declared at start."""
    return DIAGNOSTIC_CALLS + max(0, max_questions) * worst_case_question_calls(max_turns) + STUDY_PLAN_CALLS


def worst_case_session_tokens(max_questions: int, max_turns: int) -> int:
    """The per-run ceiling: what a Session CANNOT exceed without something being wrong.

    Scaled to the Session's own declared rails rather than flat, because those rails are the size
    contract the operator already chose. A flat number is loose exactly where the risk is — it would
    let a 1-question Session burn a 5-question ceiling before anyone noticed — and fires on
    compliant behaviour at the other end, suspending a legitimately long interview. Sizing the rail
    off ``max_questions``/``max_turns`` makes it "spend this Session cannot explain", which is the
    only definition of runaway that is not a guess.
    """
    return worst_case_session_calls(max_questions, max_turns) * WORST_CASE_TOKENS_PER_CALL


def session_token_budget(*, max_questions: int, max_turns: int) -> int:
    """Tokens THIS RUN of the Session may spend. ``LLM_SESSION_TOKEN_BUDGET`` overrides (flat)."""
    ceiling = min(
        # The `min` binds only in degenerate shapes (no questions, an absurd max_turns); it is kept so
        # the rail can never exceed what the Session could possibly cost.
        worst_case_session_tokens(max_questions, max_turns),
        session_ceiling_multiple(max_turns) * estimated_session_tokens(max_questions),
    )
    return _env_int("LLM_SESSION_TOKEN_BUDGET", ceiling)


def daily_question_cap() -> int:
    return _env_int("COACH_DAILY_QUESTION_CAP", DEFAULT_DAILY_QUESTION_CAP)


def estimated_session_tokens(n_questions: int, *, include_setup: bool = True) -> int:
    """What a Session of ``n_questions`` is EXPECTED to cost, from the measured constants above.

    The typical-cost estimate, not the ceiling: it answers "will this fit in what is left of the
    day?" for the start gate, where over-estimating refuses Sessions the day could have paid for.
    ``worst_case_session_tokens`` answers the opposite question and is far larger by design — it is
    NOT the runaway ceiling; ``session_ceiling_multiple`` times this estimate is (NEW-09).

    ``include_setup=False`` is the *remaining* cost mid-Session: the Diagnostic already ran and is
    not paid for twice.
    """
    setup = SESSION_SETUP_TOKENS if include_setup else 0
    return setup + max(0, n_questions) * SESSION_TOKENS_PER_QUESTION


# --- the runaway rail: the admission estimate, times what a COMPLIANT Session can add to it --------
#
# The worst-case model multiplies every call by its retry budget AND by the failover factor: at
# max_questions=10 that is 2,116,800 tokens, 85% of the whole day, and ~40x the ~53,000 the SAME
# Session was admitted on by `start_refusal_reason`. A rail 40x the model the gate admitted on is not
# a rail — one Candidate can legitimately spend the day and nothing but the day counter notices. So
# the ceiling is sized on the estimate itself, and the multiple is DERIVED from the same measured
# constants, not chosen: a future tuner has to move a number with a ledger behind it.
MEASURED_CALLS_PER_QUESTION = 3  # the measured clusters above: 1 Diagnostic + 5x3 + 1 planner
MEASURED_SESSION_CALLS = 16  # the 26,866-token cluster above, i.e. 1,679 tokens/call
COMMITTEE_CALLS = PANEL_CALLS - 2 * STRUCTURED_ATTEMPTS - (EVALUATION_CALLS - JUDGE_ATTEMPTS)
# A call can be bigger than that measured mean: the largest single call in the ledger is 2,700
# (rounded) against 26,866/16 = 1,679 per call — 1.61x.
CALL_SIZE_INFLATION = WORST_CASE_TOKENS_PER_CALL * MEASURED_SESSION_CALLS / HEAVIEST_MEASURED_SESSION_TOKENS


def compliant_question_calls(max_turns: int) -> int:
    """Calls one question makes with NO retry firing — every turn used, one committee, follow-ups.

    The measured clusters the estimate comes from were single-turn questions with no committee, so
    the estimate alone would suspend a legitimately long interview. This is the same call model as
    ``worst_case_question_calls`` with every retry multiplier set to 1.
    """
    turns = max(1, max_turns)
    return (
        1  # seed render (vn/mixed; `en` makes none)
        + turns  # one judgment per turn
        + PANEL_ESCALATIONS_PER_QUESTION * COMMITTEE_CALLS  # skeptic + advocate + re-judgment
        + (turns - 1) * 2  # each follow-up: the forced lookup_concept call, then the final answer
        + 1  # supervisor
    )


def session_ceiling_multiple(max_turns: int) -> int:
    """How many times its own admitted estimate a Session may spend before it is a runaway."""
    return math.ceil(CALL_SIZE_INFLATION * compliant_question_calls(max_turns) / MEASURED_CALLS_PER_QUESTION)


class SessionBudgetSuspended(RuntimeError):
    """A Session hit a budget rail mid-run and must suspend (ADR 0005's third category).

    Raised ONLY by the Session drivers, never inside the graph. That siting is the whole design:
    ``supervisor.question_node``'s ``except Exception`` net would otherwise convert it into a
    zero-evidence ``failed`` question and advance — the exact corruption ADR 0005 forbids. A plain
    ``RuntimeError`` is therefore safe; it never passes through a failure-isolation net.
    """


class AccountingUnavailable(RuntimeError):
    """Usage accounting is not in a state where another metered call may be made (M0a / F1).

    Raised at the provider call boundary — the last point at which a call can still be *not made* —
    and, unlike an ordinary provider failure, re-raised past ``question_node``'s
    failure-isolation net. Same reasoning as ``CandidateIntent`` and the budget rail (ADR 0005): a
    refusal to spend says nothing about the Candidate, so recording it as a zero-evidence ``failed``
    question would manufacture exactly the fake evidence that ADR forbids. ``RuntimeError`` rather
    than a ``ValueError``: ``chat_json`` retries ``(ValidationError, ValueError)``, and a gate that
    the caller retries three times is not a gate.
    """


class ProviderQuotaExhausted(RuntimeError):
    """The provider's terminal ``insufficient_quota`` (GH #119, ADR 0005's third category).

    Re-raised past every failure-isolation net exactly like :class:`AccountingUnavailable`: a dead
    quota says nothing about the Candidate. The drivers turn it into a suspend with a resume path.
    """


# Which Session (if any) the calls on this thread belong to. A ContextVar rather than a parameter
# threaded through every agent: ``record_usage`` is called from deep inside the provider clients,
# and langgraph runs sync nodes in a copied context, so a scope entered by the driver is visible in
# every node it drives (verified end-to-end by the attribution tests).
_SESSION_ID: ContextVar[str] = ContextVar("interview_coach_usage_session", default="")


@contextmanager
def session_scope(session_id: str) -> Iterator[None]:
    """Attribute every ledger row written inside this block to ``session_id``.

    The noise counters (telemetry.py) are scoped here too, and for the same reason: they count events
    raised by these very calls. The web API runs one thread per Session, so a process-wide Counter let
    one Candidate's sanitizer fold be read as another Candidate's judgment noise and haircut a clean
    confidence — infrastructure noise becoming Skill evidence (ADR 0005).
    """
    token = _SESSION_ID.set(session_id)
    try:
        with telemetry.session_counters():
            yield
    finally:
        _SESSION_ID.reset(token)


def _now_ts() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record_usage(
    provider: str,
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    path: Path | None = None,
) -> None:
    """Append one call's token usage to the ledger.

    Never raises: the provider has already answered and the caller is mid-judgment. A write that
    fails here latches an **unreconciled** accounting fault instead — the call was billed, so the
    day's spend is now undetermined, and the next metered call is refused rather than made blind.
    """
    entry: dict[str, object] = {
        "ts": _now_ts(),
        "provider": provider,
        "model": model,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
    }
    if session_id := _SESSION_ID.get():
        # Absent outside a Session (bench, forge, one-off commands) — those stay honestly
        # unattributed rather than being bucketed under a made-up id.
        entry["session"] = session_id
    _append(entry, path)


def record_questions(identity: str, questions: int, *, path: Path | None = None) -> None:
    """Reserve ``questions`` against ``identity``'s daily product cap.

    Reserved when a Session STARTS, not when it completes: a cap that only counts finished Sessions
    is bypassed by abandoning them.
    """
    _append(
        {"ts": _now_ts(), "kind": "questions", "identity": identity, "questions": int(questions)},
        path,
    )


def record_questions_released(identity: str, questions: int, *, session: str = "", path: Path | None = None) -> None:
    """Hand ``questions`` back to ``identity``'s daily cap — the compensating row for a reservation.

    A compensating ROW of its own kind, not a mutation and not a negative count on a ``questions``
    row: the ledger is append-only, and every other undo in it already works this way —
    ``quota_retry`` answers ``quota_exhausted``, a new ``session_run`` baseline answers the previous
    one, and both are resolved by scanning in write order. A negated value would also be
    indistinguishable from a corrupt reservation in a torn line. It is invisible to every token
    reader for the same reason a reservation is: it carries no token fields at all.
    """
    entry: dict[str, object] = {
        "ts": _now_ts(),
        "kind": "questions_released",
        "identity": identity,
        "questions": int(questions),
    }
    if session:
        # Not read by any rail — it is what makes a stray or doubled release traceable in a file
        # people paste into bug reports.
        entry["session"] = session
    _append(entry, path)


def record_quota_exhausted(provider: str, *, path: Path | None = None) -> None:
    """Latch ``provider``'s terminal ``insufficient_quota`` (ADR 0005's detection half, PR #89).

    Written to the ledger rather than held in a module global so it survives the process: the CLI is
    a fresh process per invocation, and a latch that forgets on exit would let the next `coach
    session` walk into the same dead quota and discover it one wasted call at a time.
    """
    _append({"ts": _now_ts(), "kind": "quota_exhausted", "provider": provider}, path)


def clear_quota_exhausted(provider: str, *, session: str = "", path: Path | None = None) -> None:
    """Un-latch the quota so ``session``'s resume gets one real attempt at the provider.

    The latch cannot expire on its own before 00:00 UTC, and a Candidate whose Session is suspended
    on it makes no calls — so nothing would ever clear it and the resume ADR 0005 promises would
    loop forever. A resume is the human saying "try again": it costs at most one call to find out,
    and if the quota really is still spent, the very next call re-latches.

    The grant is SCOPED to the resuming Session id, carried on the row and resolved by the same
    write-order scan every other undo in this ledger uses. It is one human saying "try again" about
    their own interview, not a fact about the account: left global, A's resume un-latched the provider
    for B, C and D, who then passed the start gate and each died on their first call. Evidence of LIFE
    stays global — a call that actually billed tokens is a fact about the account and clears the latch
    for everybody. ``session=""`` writes the old unscoped grant, which still clears for everyone: that
    is an operator saying "the account is fine now".
    """
    entry: dict[str, object] = {"ts": _now_ts(), "kind": "quota_retry", "provider": provider}
    if session:
        entry["session"] = session
    _append(entry, path)


# --- accounting health (M0a / F1) ---------------------------------------------------------------
#
# The rails above are arithmetic over the ledger. Arithmetic over a file that is not being written
# is not conservative — it reads as "spent nothing", which is the most permissive answer there is.
# In the stock container that was not hypothetical: the default ledger path resolves to /app/logs,
# /app is root:root 755, the process is uid 10001, so every `mkdir` failed, every row was dropped
# with a warning, and every rail happily reported a full budget for as long as the deployment ran.
#
# So a failed write latches, and a latch blocks metered work. The latch is BOTH in-process (free to
# check on the hot path, and correct even when nothing at all can be written) and on disk beside the
# ledger (so it survives the process, which is the only way a CLI — one process per invocation —
# could remember it at all).

_FAULT_LOCK = Lock()
# Faults raised by THIS process, each with whether its sidecar row made it to disk. Kept even after
# a successful flush so a reader never has to choose between two sources of truth mid-write.
_FAULTS: list[dict[str, Any]] = []
# Ledger paths whose writability has been proven in this process. Only successes are remembered: a
# failure must be re-probed, or an operator who fixes the path would still be refused until restart.
_PROVEN_WRITABLE: set[str] = set()


def _write_row(entry: Mapping[str, object], target: Path) -> None:
    """Append one JSONL row, raising ``OSError`` — the one place that actually touches the ledger."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(entry)) + "\n")


def _new_fault_id() -> str:
    """A unique key for one latched fault, so replaying it twice can be refused.

    Random rather than derived from the row: ``ts`` has one-second resolution, so two identical
    billed calls in the same second would key the same and one real charge would be forgiven — the
    single outcome this module exists to prevent. Module-level so a test can pin it.
    """
    return uuid4().hex


def _flush_faults(target: Path) -> None:
    """Best-effort: park every not-yet-parked fault in the sidecar beside ``target``.

    Write and mark under ONE hold of the lock: two Sessions flushing concurrently used to snapshot
    the same unparked fault and both append it, and a sidecar row duplicated that way is spend the
    reconcile then invents.
    """
    sidecar = ledger_fault_path(target)
    with _FAULT_LOCK:
        for fault in _FAULTS:
            if fault["parked"]:
                continue
            try:
                _write_row(fault["record"], sidecar)
            except OSError as err:
                # Expected whenever the ledger is unwritable because its *directory* is: the sidecar
                # lives in that same directory. The in-process latch still blocks this process, and
                # the writability probe still blocks the next one — see `accounting_block_reason`.
                logger.error(
                    "accounting fault could not be parked in %s (%s: %s); it is held in memory only "
                    "and will be lost if this process exits",
                    sidecar,
                    type(err).__name__,
                    err,
                )
                return
            fault["parked"] = True


def _latch_fault(entry: Mapping[str, object], err: OSError, target: Path) -> None:
    """Record that a ledger row could not be written, and refuse metered work until it is resolved."""
    # A token row is the only kind written AFTER the provider has been paid. Every other kind is
    # bookkeeping we can replay for free, so only this one leaves the day's spend undetermined.
    billed = "prompt_tokens" in entry
    record: dict[str, Any] = {
        "ts": _now_ts(),
        "id": _new_fault_id(),
        "kind": "accounting_fault",
        "row": str(entry.get("kind", "tokens")),
        "billed": billed,
        "ledger": str(target),
        "error": f"{type(err).__name__}: {err}",
        "entry": dict(entry),
    }
    with _FAULT_LOCK:
        _FAULTS.append({"record": record, "parked": False})
    logger.error(
        "usage ledger write FAILED (%s: %s) for a %s row at %s — %s. Metered calls are refused "
        "until this is reconciled (`coach usage --reconcile`).",
        type(err).__name__,
        err,
        record["row"],
        target,
        "the call was already billed, so the day's spend is now UNDETERMINED" if billed else "no spend is unaccounted",
    )
    _flush_faults(target)


def record_unmeasured_call(provider: str, model: str, *, detail: str, path: Path | None = None) -> None:
    """Latch a call the provider answered but did not state a usable token count for.

    The same fault :func:`_latch_fault` raises for a row that would not write, and for the same
    reason: the call was billed, so the day's spend is now undetermined. What it deliberately does
    NOT carry is an ``entry`` — there is no row to replay, because the cost is not known. That makes
    :func:`reconcile_accounting` report it exactly as it reports a fault whose row was lost ("that
    spend stays unknown, not zero") rather than folding a fabricated 0 into the day's total, which is
    the one answer a ledger may never invent.
    """
    target = path or ledger_path()
    record: dict[str, Any] = {
        "ts": _now_ts(),
        "id": _new_fault_id(),
        "kind": "accounting_fault",
        "row": "tokens_unmeasured",
        "billed": True,
        "ledger": str(target),
        "error": detail,
        "provider": provider,
        "model": model,
    }
    if session_id := _SESSION_ID.get():
        # No ``entry`` to carry it, so it is stamped here or lost — which Session spent the unknown
        # amount is the first question anyone reading this sidecar will ask.
        record["session"] = session_id
    logger.error(
        "%s/%s answered but stated no usable token count (%s) — the call was billed and its cost is "
        "UNKNOWN, so it is held as an accounting fault rather than recorded as zero. Metered calls "
        "are refused until this is reconciled (`coach usage --reconcile`).",
        provider,
        model,
        detail,
    )
    with _FAULT_LOCK:
        _FAULTS.append({"record": record, "parked": False})
    _flush_faults(target)


def _append(entry: dict[str, object], path: Path | None) -> None:
    """Append one ledger row. Never raises; a failure latches an accounting fault instead."""
    target = path or ledger_path()
    try:
        _write_row(entry, target)
    except OSError as err:
        _latch_fault(entry, err, target)


def _unreadable_fault(target: Path, sidecar: Path, error: str, *, whole_file: bool) -> dict[str, Any]:
    """A fault standing in for held rows we cannot read. Unknown spend, never forgiven spend.

    ``billed`` is True on purpose: the one answer that must never be *inferred* from "cannot read" is
    "nothing was spent". It carries no ``entry``, so :func:`reconcile_accounting` already counts it
    exactly as it counts a fault whose row was never parked — lost, and said out loud.
    """
    return {
        "ts": _now_ts(),
        "kind": "accounting_fault",
        "row": "unreadable_sidecar" if whole_file else "unreadable_row",
        "billed": True,
        "ledger": str(target),
        "unreadable": str(sidecar),
        "error": error,
    }


def _parked_faults(target: Path) -> list[dict[str, Any]]:
    """Every unresolved fault: the sidecar's rows, plus anything this process could not park."""
    faults: list[dict[str, Any]] = []
    sidecar = ledger_fault_path(target)
    try:
        text = sidecar.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        # The only two errors that mean "nothing is parked here" rather than "something may be parked
        # here and we cannot see it": no file, or no directory that could hold one. Both are the
        # healthy shape — on a working deployment the sidecar never exists at all.
        text = ""
    except (OSError, UnicodeDecodeError) as err:
        # It is there and we cannot read it. A sidecar left 0600 root:root by an older container while
        # the ledger itself was repaired is exactly the permission class this slice exists for.
        # Reading that as "no faults" is the most permissive answer there is, drawn from the least
        # readable input, and it lets metered work resume over spend that may still be unaccounted
        # for. So the unreadable sidecar IS the unresolved fault until someone can read it.
        logger.error(
            "the held-row sidecar at %s exists but could not be read (%s: %s); metered calls are "
            "refused until it can be, because what it holds may be a billed call",
            sidecar,
            type(err).__name__,
            err,
        )
        faults.append(_unreadable_fault(target, sidecar, f"{type(err).__name__}: {err}", whole_file=True))
        text = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as err:
            # A torn last line is a parked row whose write was cut short: unparseable, but evidence
            # that something WAS parked. Skipping it is the same forgiveness as above, one row at a
            # time, so it becomes a fault carrying no replayable row instead.
            logger.error("a row in %s could not be parsed (%s); it is held as unknown spend, not dropped", sidecar, err)
            faults.append(_unreadable_fault(target, sidecar, f"{type(err).__name__}: {err}", whole_file=False))
            continue
        if isinstance(row, dict):
            faults.append(row)
        else:
            logger.error("a row in %s is not a JSON object (%r); it is held as unknown spend", sidecar, row)
            faults.append(_unreadable_fault(target, sidecar, "row is not a JSON object", whole_file=False))
    with _FAULT_LOCK:
        faults.extend(fault["record"] for fault in _FAULTS if not fault["parked"])
    return faults


def accounting_fault(*, path: Path | None = None) -> str | None:
    """The unresolved accounting condition blocking metered work, or None.

    Cheap enough for the per-call gate: one ``stat``-shaped read of a file that does not exist on
    any healthy deployment. It reports only *latched* faults — a write that already failed — never
    the writability of the path, which :func:`check_ledger_writable` owns.
    """
    target = path or ledger_path()
    faults = _parked_faults(target)
    if not faults:
        return None
    # Retry parking now: the fault may have been raised while the directory was unwritable and
    # survived only in memory. Once it is on disk it outlives this process, which is the difference
    # between a remembered fault and a forgotten one.
    _flush_faults(target)
    if unreadable := [fault for fault in faults if fault.get("unreadable")]:
        # First, because it is the stronger statement: this is not a report of what the held rows say,
        # it is a report that we cannot read them. Whether one of them is a billed call is unknown —
        # and unknown is not zero.
        return (
            f"Usage accounting is UNRECONCILED: {len(unreadable)} held row(s) beside the ledger at "
            f"{target} cannot be read ({unreadable[0].get('error')}). The sidecar "
            f"{ledger_fault_path(target)} exists only because a ledger write failed, so its contents "
            f"are unknown spend, not zero spend, and metered calls are refused until it can be read. "
            f"Restore read access to that file (in the container it belongs to the same uid as the "
            f"ledger, 10001), then run `coach usage --reconcile`."
        )
    billed = [fault for fault in faults if fault.get("billed")]
    if billed:
        tokens = 0
        for fault in billed:
            row = fault.get("entry")
            if isinstance(row, dict):
                try:
                    tokens += int(row.get("prompt_tokens", 0)) + int(row.get("completion_tokens", 0))
                except (TypeError, ValueError):
                    continue
        return (
            f"Usage accounting is UNRECONCILED: {len(billed)} provider call(s) were billed but could "
            f"not be recorded in the token ledger at {target} (~{tokens:,} token(s) held in "
            f"{ledger_fault_path(target)}). Until they are folded back in, every budget rail here "
            f"under-counts the day, so metered calls are refused rather than made against a number "
            f"we know is wrong — an unrecorded call is not a free one. Make the ledger path writable, "
            f"then run `coach usage --reconcile` to replay the held rows and clear this."
        )
    return (
        f"Usage accounting is degraded: {len(faults)} ledger row(s) could not be written to {target} "
        f"and are held in {ledger_fault_path(target)}. No provider call is unaccounted for — the held "
        f"rows are budget bookkeeping — but the rails read an incomplete ledger until they are "
        f"replayed. Make the ledger path writable, then run `coach usage --reconcile`."
    )


def check_ledger_writable(*, path: Path | None = None) -> str | None:
    """Why the ledger cannot be written, or None. The check that runs BEFORE anything is spent.

    Distinct from :func:`accounting_fault` on purpose, and the distinction is the whole point of
    this slice: this condition means no metered call has been made under it, so there is no spend to
    reconcile — fixing the path is the entire remedy. Probing by opening the file in append mode
    rather than by ``os.access``: the mode bits are not the question, "will the next append work" is.
    """
    target = path or ledger_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8"):
            pass
        # Read too, not only append: every rail above COUNTS this file, so a ledger we can write and
        # cannot read still leaves the day's spend unknown. The append above has just created it, so
        # on a healthy path this always succeeds.
        with target.open("r", encoding="utf-8"):
            pass
    except OSError as err:
        return (
            f"Usage accounting is unavailable: the token ledger at {target} cannot be written "
            f"({type(err).__name__}: {err}). Every metered call is refused while this holds, because "
            f"a call nobody records is spend nobody can see. Nothing is unaccounted for yet — no "
            f"metered call has been made under this condition. Point COACH_USAGE_LEDGER at a writable "
            f"path (in the container that means the state volume, e.g. /app/state/usage-ledger.jsonl) "
            f"or grant the running user (uid 10001 in this image) write access to it."
        )
    return None


def accounting_block_reason(*, path: Path | None = None) -> str | None:
    """The single gate every rail shares: an unresolved fault first, then the path itself.

    Fault first because it is the stronger statement — a path that is writable *again* does not
    un-spend the call whose row never landed.
    """
    return accounting_fault(path=path) or check_ledger_writable(path=path)


def accounting_gate(*, path: Path | None = None) -> str | None:
    """The gate at the provider call boundary, cheap after the first call in a process.

    A latched fault is always checked. The writability probe runs once per ledger path per process
    and only its SUCCESS is remembered: a failure is re-probed every call, which costs nothing on a
    path that is already refusing work, and means an operator who fixes the path is unblocked
    without a restart. The one-per-process probe is what closes the gap the start rails leave — the
    bench, the forge and any other direct caller never pass through ``start_refusal_reason``, and
    without it their FIRST call would be billed before the missing row latched anything.
    """
    if fault := accounting_fault(path=path):
        return fault
    target = path or ledger_path()
    key = str(target)
    if key in _PROVEN_WRITABLE:
        return None
    reason = check_ledger_writable(path=target)
    if reason is None:
        _PROVEN_WRITABLE.add(key)
    return reason


def reconcile_accounting(*, path: Path | None = None) -> str:
    """Replay every held row into the ledger and clear the fault. Raises ``OSError`` if it cannot.

    Reconciliation replays rather than forgives: the held rows carry the token counts the provider
    actually charged, so folding them back in restores the true day total. Treating them as zero —
    which is what "just clear the flag" would do — is the one outcome this slice exists to prevent.
    """
    target = path or ledger_path()
    faults = _parked_faults(target)
    if not faults:
        return "No accounting fault to reconcile."
    if any(fault.get("row") == "unreadable_sidecar" for fault in faults):
        # Everything below ends by rewriting the sidecar to hold exactly what it could not replay —
        # which, for a file we were never able to read, is nothing. That would delete the held rows
        # and report success. Refuse instead: nothing read, nothing replayed, nothing cleared.
        raise OSError(
            f"the held-row sidecar at {ledger_fault_path(target)} cannot be read, so its rows cannot "
            f"be replayed; nothing was changed and metered calls stay refused"
        )
    replayed = 0
    tokens = 0
    skipped = 0
    unreplayed: list[dict[str, Any]] = []
    failure: OSError | None = None
    # The idempotency key, read back from the ledger itself rather than held anywhere: a replay that
    # landed is already stamped there, so a duplicate sidecar row — or a retry after the rewrite
    # below failed — cannot bill the same call a second time.
    done = _replayed_fault_ids(target)
    for fault in faults:
        row = fault.get("entry")
        if not isinstance(row, dict):
            # A fault whose row could not be parked and whose process has since exited: we know a
            # call went unrecorded but not what it cost. Said out loud below rather than rounded to 0.
            continue
        if failure is not None:
            unreplayed.append(fault)
            continue
        fault_id = fault.get("id")
        if isinstance(fault_id, str) and fault_id:
            if fault_id in done:
                # Already folded in: a row two concurrent flushes parked twice, or a retry after the
                # sidecar rewrite below failed. Replaying it again would INVENT spend.
                skipped += 1
                continue
            # Copied, not mutated: `fault["entry"]` may still be the live `_FAULTS` record.
            row = {**row, "fault": fault_id}
        try:
            _write_row(row, target)
        except OSError as err:
            # Stop at the first failure and keep the rest held. Carrying on would only lose more
            # rows, and leaving an already-replayed row in the sidecar would double-count it on the
            # next attempt — over-counting a day's spend is safer than losing it, but it is still wrong.
            failure = err
            unreplayed.append(fault)
            continue
        if isinstance(fault_id, str) and fault_id:
            done.add(fault_id)
        replayed += 1
        try:
            tokens += int(row.get("prompt_tokens", 0)) + int(row.get("completion_tokens", 0))
        except (TypeError, ValueError):
            pass
    lost = len(faults) - replayed - skipped - len(unreplayed)
    _rewrite_fault_sidecar(target, unreplayed)
    _PROVEN_WRITABLE.discard(str(target))
    if failure is not None:
        raise failure
    note = f"Reconciled {replayed} held ledger row(s) into {target} (~{tokens:,} token(s) restored)."
    if skipped:
        note += f" {skipped} held row(s) were already in the ledger and were NOT replayed again."
    if lost:
        note += f" {lost} fault(s) carried no replayable row; that spend stays unknown, not zero."
    return note


def _replayed_fault_ids(target: Path) -> set[str]:
    """Fault ids already folded into ``target`` — what makes a second ``--reconcile`` a no-op."""
    return {str(row["fault"]) for row in _all_rows(target) if isinstance(row.get("fault"), str)}


def _rewrite_fault_sidecar(target: Path, faults: list[dict[str, Any]]) -> None:
    """Leave exactly ``faults`` held, and drop the in-process copies now accounted for either way."""
    sidecar = ledger_fault_path(target)
    with _FAULT_LOCK:
        _FAULTS.clear()
    if not faults:
        sidecar.unlink(missing_ok=True)
        return
    body = "".join(json.dumps(fault) + "\n" for fault in faults)
    try:
        sidecar.write_text(body, encoding="utf-8")
    except OSError as err:
        # The sidecar is where the unreplayed rows live, so failing to rewrite it is the one case
        # that can lose them. Loud, and re-latched in memory so this process still refuses to spend.
        logger.error(
            "could not rewrite %s (%s: %s); %d held row(s) are in memory only",
            sidecar,
            type(err).__name__,
            err,
            len(faults),
        )
        with _FAULT_LOCK:
            _FAULTS.extend({"record": fault, "parked": False} for fault in faults)


def reset_accounting_state() -> None:
    """Forget this process's latched faults and writability probes (test isolation only)."""
    with _FAULT_LOCK:
        _FAULTS.clear()
    _PROVEN_WRITABLE.clear()


def _all_rows(path: Path | None) -> Iterator[dict]:
    """Every parseable ledger row, any day, in write order. One corrupt line must not hide the rest."""
    target = path or ledger_path()
    if not target.exists():
        return
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as err:
        # A ledger that cannot be READ is as broken as one that cannot be written, and it must not
        # take a rail down with a traceback. Returning nothing here would read as "spent nothing",
        # so this is never the last line of defence: `check_ledger_writable` probes the read too,
        # and every rail checks it before counting anything.
        logger.error("usage ledger at %s could not be read (%s: %s)", target, type(err).__name__, err)
        return
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            yield entry


def _rows_for_day(day: str, path: Path | None) -> Iterator[dict]:
    """Every parseable ledger row stamped ``day``."""
    for entry in _all_rows(path):
        try:
            if str(entry["ts"]).startswith(day):
                yield entry
        except KeyError:
            continue


def token_identity(auth_token: str) -> str:
    """The product-cap bucket for a deployment's shared secret.

    Deliberate simplification: there is exactly ONE valid shared secret today (R-07), so per-identity
    is per-deployment and the bucket is derivable from ``settings.auth_token`` alone — which is what
    keeps the auth path (``authenticate_socket``/``token_matches``) untouched by this rail. The
    ``identity`` parameter is the seam that becomes per-user when real accounts land (R-29).

    Digested, never stored raw: the ledger is a plain-text file that gets pasted into bug reports.
    """
    if not auth_token.strip():
        return "anonymous"
    return sha256(auth_token.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def usage_for_day(day: str | None = None, *, path: Path | None = None) -> dict[str, dict[str, int]]:
    """Per-provider token totals for one UTC day (default: today).

    Returns ``{provider: {"prompt": ..., "completion": ..., "total": ..., "calls": ...}}``.
    Malformed lines are skipped: the ledger is advisory, and one corrupt line must not hide the
    rest of the day's spend.
    """
    totals: dict[str, dict[str, int]] = {}
    for entry in _rows_for_day(day or utc_date(), path):
        try:
            prompt, completion = int(entry["prompt_tokens"]), int(entry["completion_tokens"])
            provider = str(entry["provider"])
        except (KeyError, TypeError, ValueError):
            # Also how a non-token row stays invisible here: it carries no token fields at all.
            continue
        bucket = totals.setdefault(provider, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["total"] += prompt + completion
        bucket["calls"] += 1
    return totals


def sessions_for_day(day: str | None = None, *, path: Path | None = None) -> dict[str, int]:
    """Per-Session-id token totals for one UTC day. Unattributed rows group under ``""``.

    An id, not a run: `coach usage` reports what a name cost today, which is the right question for
    a human reading a ledger and the WRONG one for the rail (see ``session_run_spend``).
    """
    totals: dict[str, int] = {}
    for entry in _rows_for_day(day or utc_date(), path):
        try:
            spent = int(entry["prompt_tokens"]) + int(entry["completion_tokens"])
        except (KeyError, TypeError, ValueError):
            continue
        session = str(entry.get("session", ""))
        totals[session] = totals.get(session, 0) + spent
    return totals


def session_spend(session_id: str, *, day: str | None = None, path: Path | None = None) -> int:
    """Tokens this Session id has spent today, across every provider and every run under that id."""
    return sessions_for_day(day, path=path).get(session_id, 0)


# --- per-RUN accounting --------------------------------------------------------------------------
#
# ``session`` on a token row is a Session *id*, and ids are reused by default on both surfaces: the
# CLI's ``--session-id`` defaults to the constant "local-session", and the web persists one id per
# browser in localStorage, rotating it only when the Candidate explicitly asks for a new Session.
# Summing an id's rows therefore measures "everything ever run under this name", not "this
# interview" — a rail built on that number suspends the day's third interview for spending nothing
# of its own, and once tripped the id is a dead end until 00:00 UTC.
#
# So a run stamps a baseline when it starts and the rail measures the delta. The baseline is
# PERSISTED, not held in memory, precisely so ``--resume`` continues the same run's accounting: a
# resume that re-snapshotted would hand out a fresh full budget every time and the rail would bound
# nothing at all. Clearing it is a deliberate, recorded act — see ``extend_budget_for_resume``.


def session_lifetime_spend(session_id: str, *, path: Path | None = None) -> int:
    """Every token ever attributed to this Session id, across UTC days.

    Not day-scoped, unlike ``session_spend``: a run suspended at 23:59 and resumed at 00:01 is ONE
    run, and an accounting that forgot yesterday's half of it would hand a runaway a second budget
    at midnight for free.
    """
    total = 0
    for entry in _all_rows(path):
        if str(entry.get("session", "")) != session_id:
            continue
        try:
            total += int(entry["prompt_tokens"]) + int(entry["completion_tokens"])
        except (KeyError, TypeError, ValueError):
            continue
    return total


def session_baseline(session_id: str, *, path: Path | None = None) -> int:
    """The lifetime spend the current run started from — the latest ``session_run`` row, else 0.

    0 covers a Session checkpointed before this rail existed. That measures such a Session from its
    first ever recorded token, which over-counts rather than under-counts; for a spend rail, erring
    toward suspending is the safe direction, and the next fresh start on the id corrects it.
    """
    baseline = 0
    for entry in _all_rows(path):
        if entry.get("kind") != "session_run" or str(entry.get("session", "")) != session_id:
            continue
        try:
            baseline = int(entry["baseline"])
        except (KeyError, TypeError, ValueError):
            continue
    return baseline


def begin_session_run(session_id: str, *, path: Path | None = None) -> int:
    """Stamp the start of a run under ``session_id`` and return the baseline it will measure from."""
    baseline = session_lifetime_spend(session_id, path=path)
    _append({"ts": _now_ts(), "kind": "session_run", "session": session_id, "baseline": baseline}, path)
    return baseline


def session_run_spend(session_id: str, *, path: Path | None = None) -> int:
    """Tokens THIS run has spent — the number the per-run rail compares against its budget."""
    return max(0, session_lifetime_spend(session_id, path=path) - session_baseline(session_id, path=path))


def quota_exhausted_today(
    provider: str, *, session: str = "", day: str | None = None, path: Path | None = None
) -> bool:
    """Whether ``provider`` last told us its allowance is spent, and nothing has succeeded since.

    Scanned in write order so any later evidence of life — an explicit ``quota_retry`` from a resume,
    or simply a call that succeeded and billed tokens — clears the latch. Day-scoped because the
    allowance itself resets at 00:00 UTC.

    ``session`` is who is asking. A ``quota_retry`` is one Session's granted attempt and answers the
    latch only for that Session; a token row is the account itself proving it is alive and answers it
    for everyone. A caller with no Session to name (a fresh start) therefore still sees the dead quota
    somebody else was granted a retry against.
    """
    dead = False
    for entry in _rows_for_day(day or utc_date(), path):
        if str(entry.get("provider", "")) != provider:
            continue
        kind = entry.get("kind")
        if kind == "quota_exhausted":
            dead = True
        elif kind == "quota_retry":
            granted = str(entry.get("session", ""))
            if not granted or granted == session:
                dead = False
        elif "prompt_tokens" in entry:
            dead = False
    return dead


def questions_today(identity: str, *, day: str | None = None, path: Path | None = None) -> int:
    """Questions ``identity`` still holds against the product cap today: reserved minus released.

    A run that ends without asking what it reserved gives the remainder back (web_api's
    ``_release_unused_questions``), so this measures OUTSTANDING reservations rather than every
    reservation ever taken. Never negative: a release only ever answers a reservation, and if one is
    ever written without its pair, 0 is the honest floor rather than a credit against the next start.
    """
    total = 0
    for entry in _rows_for_day(day or utc_date(), path):
        kind = entry.get("kind")
        if kind not in {"questions", "questions_released"} or str(entry.get("identity", "")) != identity:
            continue
        try:
            count = int(entry["questions"])
        except (KeyError, TypeError, ValueError):
            continue
        total += -count if kind == "questions_released" else count
    return max(0, total)


def remaining_today(provider: str = "openai", *, path: Path | None = None) -> int:
    """Tokens left in today's budget by our own count, across EVERY provider (never negative).

    ``provider`` names the provider the caller is about to spend on — it is what the refusal sentences
    quote — but it deliberately does NOT narrow the sum. ``LLM_DAILY_TOKEN_BUDGET`` is one scalar, and
    a failover bills a SECOND provider for the same logical call, so a per-provider bucket reports a
    budget that is already spent; once the primary's circuit breaker opens, every call bills only the
    fallback and a per-provider rail never fires at all.
    """
    spent = sum(bucket.get("total", 0) for bucket in usage_for_day(path=path).values())
    return max(0, daily_token_budget() - spent)


# --- refusal / suspend reasons: ONE implementation, so CLI and web say the same thing ------------
#
# Every reason states the REMEDY, and states it truthfully. That is the whole difference between a
# suspend (ADR 0005: "suspends with an explicit, user-visible reason and offers resume") and a
# stall — and a remedy the reader cannot act on, or that provably loops, is a stall wearing a
# suspend's clothes. Each rail below therefore says what clears it and what happens if you resume
# before then; the tests assert those sentences against the behaviour they promise.


def daily_reset_hint(now: datetime | None = None) -> str:
    """When the allowance comes back — a countdown, because "at 00:00 UTC" is not a wait time."""
    moment = now or datetime.now(UTC)
    reset = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    hours, minutes = divmod(max(0, int((reset - moment).total_seconds())) // 60, 60)
    return f"The daily allowance resets at 00:00 UTC, ~{hours}h{minutes:02d}m from now."


def start_refusal_reason(provider: str, *, questions: int, path: Path | None = None) -> str | None:
    """Why a fresh Session must not start, or None. Checked BEFORE the first token is spent."""
    # Accounting first: every rail below is arithmetic over the ledger, so a ledger that is not
    # being written makes them all answer "plenty left" — the most permissive answer, from the least
    # reliable input. A start gate that reads a broken counter is not a gate (M0a / F1).
    if blocked := accounting_block_reason(path=path):
        return blocked
    if quota_exhausted_today(provider, path=path):
        return (
            f"The {provider} account is out of quota — the provider returned insufficient_quota and "
            f"no retry can fix that, so this Session would die on its first call. "
            f"{daily_reset_hint()}"
        )
    needed = estimated_session_tokens(questions)
    left = remaining_today(provider, path=path)
    if left >= needed:
        return None
    return (
        f"Not enough of today's {provider} budget left to run a {questions}-question Session: "
        f"~{left:,} tokens remain by our count and this Session is estimated at ~{needed:,}. "
        f"{daily_reset_hint()} Raise LLM_DAILY_TOKEN_BUDGET if your real allowance is larger, or "
        "start a shorter Session."
    )


def metered_command_refusal_reason(provider: str, *, work: str, needed: int, path: Path | None = None) -> str | None:
    """Why a metered CLI batch command must not start, or None. Checked BEFORE the first token.

    ``start_refusal_reason`` is sized in questions because a Session IS questions. A bench sweep, a
    forge batch and a debrief are not, so this one takes the token estimate its caller measured and
    names the work in the operator's own words — same three checks, same order, same remedies, one
    implementation so the CLI and the web keep saying the same thing. For the Candidate it is the
    same event either way: a `coach bench --k 3` drains the allowance their live Session is spending,
    and their Session suspends for a batch job nobody rationed (ADR 0005).

    ``quota_exhausted_today`` is asked UNSCOPED on purpose: a batch command has no Session of its
    own, so a retry granted to somebody else's resume must not answer the latch for it.
    """
    if blocked := accounting_block_reason(path=path):
        return blocked
    if quota_exhausted_today(provider, path=path):
        return (
            f"The {provider} account is out of quota — the provider returned insufficient_quota and "
            f"no retry can fix that, so {work} would die on its first call. {daily_reset_hint()}"
        )
    left = remaining_today(provider, path=path)
    if left >= needed:
        return None
    return (
        f"Not enough of today's {provider} budget left to run {work}: ~{left:,} tokens remain by "
        f"our count and it is estimated at ~{needed:,}. {daily_reset_hint()} Raise "
        f"LLM_DAILY_TOKEN_BUDGET if your real allowance is larger."
    )


def question_cap_reason(identity: str, *, questions: int, path: Path | None = None) -> str | None:
    """Why this identity may not start another Session today, or None (the product cap, AC d).

    Web-only by design, and the reasoning belongs here rather than in a workflow report: the bucket
    is a *token* identity, so it only exists where there is a token to hash. The CLI operator holds
    the provider key and owns the deployment — rationing them against their own allowance would be
    theatre, and the daily-budget and per-run rails already bound what they can spend by accident.
    When real accounts land (R-29) ``identity`` becomes per-user and this moves with them.
    """
    # Checked here as well as in `start_refusal_reason`, because `reserve_questions` is also called
    # on its own (tests, future callers). A rail that counts rows before asking whether the file can
    # be counted is a rail reading an unknown number (M0a / F1).
    if blocked := accounting_block_reason(path=path):
        return blocked
    cap = daily_question_cap()
    already = questions_today(identity, path=path)
    if already + questions <= cap:
        return None
    return (
        f"Daily question cap reached: {already} of {cap} question(s) already started today and this "
        f"Session asks for {questions} more. {daily_reset_hint()} Raise COACH_DAILY_QUESTION_CAP to "
        "lift the cap."
    )


# Check-and-record is one step: two simultaneous starts must not both read the pre-reservation count.
# One step ACROSS PROCESSES too — two `coach api` processes sharing a state volume (a compose
# `scale`, an overlapping redeploy, a second `coach api` pointed at the same COACH_USAGE_LEDGER) are
# two independent `_RESERVATION_LOCK`s over one file, and both would read the same pre-reservation
# count. The flock on the ledger's `.lock` sidecar is what makes the window exclusive, and it is
# taken INSIDE the thread lock, never outside (flock is per open file description, so the reverse
# order deadlocks two threads of this process against each other). Nothing inside this block may take
# the same file lock again: `record_questions` appends without it, and a nested acquisition on a
# second descriptor would block this process on itself.
_RESERVATION_LOCK = Lock()


def reserve_questions(identity: str, *, questions: int, path: Path | None = None) -> str | None:
    """Reserve ``questions`` against the daily cap atomically; returns the refusal reason, or None."""
    target = path or ledger_path()
    with _RESERVATION_LOCK, locked(target):
        if reason := question_cap_reason(identity, questions=questions, path=target):
            return reason
        record_questions(identity, questions, path=target)
        return None


def budget_stop_reason(
    session_id: str,
    provider: str,
    *,
    questions_left: int,
    questions_resolved: int,
    max_questions: int,
    max_turns: int,
    session_complete: bool,
    path: Path | None = None,
) -> str | None:
    """Why a running Session must suspend now, or None.

    Called by the Session drivers at the graph's node boundary, so a stop is raised OUTSIDE the
    graph and can never be recorded as a ``failed`` question (ADR 0005).
    """
    if session_complete:
        # The rail exists to stop FURTHER spending, and a Session that has reached COMPLETE has at
        # most one Study Plan call left. Suspending here would cost the whole interview: the driver
        # unwinds before saving Beta posteriors (ADR 0006), printing the summary, or writing the
        # export — a plain abort of a Session that produced real evidence, reported as a suspend.
        return None
    # Same precedence as the start gate, and for the same reason: the two rails below both read the
    # ledger. Placed AFTER the completion check on purpose — at COMPLETE the only spend left is one
    # Study Plan call, which the call-boundary gate refuses on its own (the planner node degrades),
    # so suspending here would throw away a whole interview's evidence to save a call already saved.
    if blocked := accounting_block_reason(path=path):
        return blocked
    # Scoped to THIS Session: the grant a resume writes is for this interview only, so another
    # Candidate's retry must not silently un-suspend this one, and this one's must be honoured.
    if quota_exhausted_today(provider, session=session_id, path=path):
        return (
            f"The {provider} account is out of quota (the provider returned insufficient_quota, "
            f"which no retry can fix). Suspending with {questions_resolved} question(s) resolved "
            f"rather than failing the rest. {daily_reset_hint()} Resuming re-tries the provider "
            "once; if the quota is still spent the Session suspends again at this same point."
        )
    budget = session_token_budget(max_questions=max_questions, max_turns=max_turns)
    spent = session_run_spend(session_id, path=path)
    if spent >= budget:
        return (
            f"Session {session_id!r} has spent ~{spent:,} tokens on this run, past the ~{budget:,} "
            f"a {max_questions}-question Session can possibly cost (LLM_SESSION_TOKEN_BUDGET "
            f"overrides). That is a runaway, not a long interview. Suspending with "
            f"{questions_resolved} question(s) resolved and kept in the checkpoint. Resume this "
            "Session to continue: a resume grants one more per-run budget and is recorded in the "
            "usage ledger, so do it only if the spend looks legitimate."
        )
    # A Session with nothing left to ask needs 0 from here, so the comparison below returns None on
    # its own — no separate guard, and no way for this rail to strand a Session one node from its
    # Study Plan.
    needed = estimated_session_tokens(questions_left, include_setup=False)
    left = remaining_today(provider, path=path)
    if left >= needed:
        return None
    return (
        f"Today's {provider} budget cannot fund the {questions_left} question(s) left in this "
        f"Session: ~{left:,} tokens remain by our count and ~{needed:,} are estimated. Suspending "
        f"with {questions_resolved} question(s) resolved instead of failing the rest. "
        f"{daily_reset_hint()} Resuming before then will suspend again at this same point."
    )


def session_budget_guard(
    session_id: str,
    provider: str,
    *,
    max_turns: int,
    complete_status: str,
    path: Path | None = None,
) -> Callable[[Mapping[str, Any]], str | None]:
    """The rail the Session drivers hang off every graph-node boundary.

    One implementation for both surfaces: the CLI and the web read the SAME state keys and produce
    the SAME sentence, so a rail that is right on one surface cannot silently be wrong on the other.
    ``complete_status`` is passed in rather than imported because ``SessionStatus`` lives in
    supervisor.py, which imports the provider clients, which import this module.
    """

    def guard(state: Mapping[str, Any]) -> str | None:
        max_questions = int(state.get("max_questions", 0))
        resolved = int(state.get("question_count", 0))
        return budget_stop_reason(
            session_id,
            provider,
            # The questions already resolved are already paid for; charging for them again suspends
            # a Session that can comfortably afford the rest of itself.
            questions_left=max_questions - resolved,
            questions_resolved=resolved,
            max_questions=max_questions,
            max_turns=max_turns,
            session_complete=str(state.get("status", "")) == complete_status,
            path=path,
        )

    return guard


def extend_budget_for_resume(
    session_id: str,
    *,
    max_questions: int,
    max_turns: int,
    path: Path | None = None,
) -> int | None:
    """Clear a per-run suspend so a resume can actually make progress; returns the spend it forgave.

    ADR 0005 requires a suspend to *offer resume*. The daily rails clear themselves with time, but
    the per-run ceiling never does — a run's spend only grows — so without this the rail re-trips at
    the first node boundary of every resume, forever. That is the stall the ADR forbids, and on the
    web it has no exit at all: a Candidate cannot edit ``LLM_SESSION_TOKEN_BUDGET``.

    A resume is a human saying "keep going", so it grants exactly one more per-run budget and
    records the grant. The rail keeps its teeth: what it exists to stop is an UNATTENDED runaway
    inside one drive, and nothing unattended can resume itself.
    """
    spent = session_run_spend(session_id, path=path)
    if spent < session_token_budget(max_questions=max_questions, max_turns=max_turns):
        return None
    begin_session_run(session_id, path=path)
    return spent


def clear_run_rails_for_resume(
    session_id: str,
    provider: str,
    *,
    max_questions: int,
    max_turns: int,
    path: Path | None = None,
) -> str | None:
    """Give a resume its one honest attempt at the two rails that cannot clear themselves.

    Both latch on a *condition inside this run* rather than on the clock, so both would otherwise
    loop. Returns a note for the operator when something was actually cleared, or None. The daily
    ledger rail is deliberately absent: it is arithmetic over the day, not a latch, and it clears at
    00:00 UTC whether anyone resumes or not.
    """
    notes: list[str] = []
    if forgiven := extend_budget_for_resume(session_id, max_questions=max_questions, max_turns=max_turns, path=path):
        budget = session_token_budget(max_questions=max_questions, max_turns=max_turns)
        notes.append(f"the previous run spent ~{forgiven:,} tokens; this resume grants ~{budget:,} more")
    if quota_exhausted_today(provider, session=session_id, path=path):
        clear_quota_exhausted(provider, session=session_id, path=path)
        notes.append(f"retrying {provider} after an insufficient_quota stop")
    if not notes:
        return None
    return "; ".join(notes)
