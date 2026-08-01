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

Recording must NEVER take down a live call — a lost ledger line is noise, a crashed judgment is not.
Days are UTC, matching the provider's daily reset.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

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
# Gap-clustered (>10 min) the 1,380 openai/gpt-5.4-mini rows into 10 clusters. Five carry the
# `coach session` signature — a ~450p/240c Diagnostic, then repeating evaluator/interviewer triples,
# then a ~1,800p planner call — as opposed to the 455- and 778-call bench sweeps:
#   2026-07-11T13:21  16 calls  26,866 tok  (1,679/call — the heaviest Session measured)
#   2026-07-27T05:12   4 calls   5,596 tok  (1,399/call)
#   2026-07-27T07:36  11 calls  14,616 tok  (1,329/call)
#   2026-07-27T12:21   5 calls   6,836 tok  (1,367/call)
#   2026-07-27T12:42  17 calls  21,891 tok  (1,288/call — 1 Diagnostic + 5x3 + 1 planner)
# The two bench sweeps are the largest *sustained* per-call means on record: 1,720/call over 455
# calls and 1,956/call over 778. The single largest call ever recorded is 2,663 tokens.

HEAVIEST_MEASURED_SESSION_TOKENS = 26_866
# The single largest provider call in the ledger. This — not any mean — is the right per-call figure
# for a CEILING: a runaway is precisely the case where the expensive call is the one that repeats,
# so a rail sized on the average would fire on a legitimate Session made of big prompts.
LARGEST_MEASURED_CALL_TOKENS = 2_663
WORST_CASE_TOKENS_PER_CALL = 2_700

# Measured Diagnostic calls ranged 681–993 tokens; one Diagnostic runs per Session.
SESSION_SETUP_TOKENS = 1_000
# 26,866 less its 993-token Diagnostic, over 5 questions = 5,175/question, rounded up.
SESSION_TOKENS_PER_QUESTION = 5_200

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


def worst_case_question_calls(max_turns: int) -> int:
    """Provider calls one question can cost with every retry, degrade and escalation firing."""
    turns = max(1, max_turns)
    return (
        SEED_RENDER_CALLS
        + turns * EVALUATION_CALLS
        + PANEL_ESCALATIONS_PER_QUESTION * PANEL_CALLS
        # The last turn hits the safety cap, so it never asks for a follow-up.
        + (turns - 1) * FOLLOW_UP_CALLS
        + SUPERVISOR_CALLS
    )


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
    return _env_int("LLM_SESSION_TOKEN_BUDGET", worst_case_session_tokens(max_questions, max_turns))


def daily_question_cap() -> int:
    return _env_int("COACH_DAILY_QUESTION_CAP", DEFAULT_DAILY_QUESTION_CAP)


def estimated_session_tokens(n_questions: int, *, include_setup: bool = True) -> int:
    """What a Session of ``n_questions`` is EXPECTED to cost, from the measured constants above.

    The typical-cost estimate, not the ceiling: it answers "will this fit in what is left of the
    day?" for the start gate, where over-estimating refuses Sessions the day could have paid for.
    ``worst_case_session_tokens`` answers the opposite question and is ~28x larger by design.

    ``include_setup=False`` is the *remaining* cost mid-Session: the Diagnostic already ran and is
    not paid for twice.
    """
    setup = SESSION_SETUP_TOKENS if include_setup else 0
    return setup + max(0, n_questions) * SESSION_TOKENS_PER_QUESTION


class SessionBudgetSuspended(RuntimeError):
    """A Session hit a budget rail mid-run and must suspend (ADR 0005's third category).

    Raised ONLY by the Session drivers, never inside the graph. That siting is the whole design:
    ``supervisor.question_node``'s ``except Exception`` net would otherwise convert it into a
    zero-evidence ``failed`` question and advance — the exact corruption ADR 0005 forbids. A plain
    ``RuntimeError`` is therefore safe; it never passes through a failure-isolation net.
    """


# Which Session (if any) the calls on this thread belong to. A ContextVar rather than a parameter
# threaded through every agent: ``record_usage`` is called from deep inside the provider clients,
# and langgraph runs sync nodes in a copied context, so a scope entered by the driver is visible in
# every node it drives (verified end-to-end by the attribution tests).
_SESSION_ID: ContextVar[str] = ContextVar("interview_coach_usage_session", default="")


@contextmanager
def session_scope(session_id: str) -> Iterator[None]:
    """Attribute every ledger row written inside this block to ``session_id``."""
    token = _SESSION_ID.set(session_id)
    try:
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
    """Append one call's token usage to the ledger. Swallows IO errors by design."""
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


def record_quota_exhausted(provider: str, *, path: Path | None = None) -> None:
    """Latch ``provider``'s terminal ``insufficient_quota`` (ADR 0005's detection half, PR #89).

    Written to the ledger rather than held in a module global so it survives the process: the CLI is
    a fresh process per invocation, and a latch that forgets on exit would let the next `coach
    session` walk into the same dead quota and discover it one wasted call at a time.
    """
    _append({"ts": _now_ts(), "kind": "quota_exhausted", "provider": provider}, path)


def clear_quota_exhausted(provider: str, *, path: Path | None = None) -> None:
    """Un-latch the quota so a resume gets one real attempt at the provider.

    The latch cannot expire on its own before 00:00 UTC, and a Candidate whose Session is suspended
    on it makes no calls — so nothing would ever clear it and the resume ADR 0005 promises would
    loop forever. A resume is the human saying "try again": it costs at most one call to find out,
    and if the quota really is still spent, the very next call re-latches.
    """
    _append({"ts": _now_ts(), "kind": "quota_retry", "provider": provider}, path)


def _append(entry: dict[str, object], path: Path | None) -> None:
    target = path or ledger_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as err:
        logger.warning("usage ledger write failed (%s); dropping entry %s", err, entry)


def _all_rows(path: Path | None) -> Iterator[dict]:
    """Every parseable ledger row, any day, in write order. One corrupt line must not hide the rest."""
    target = path or ledger_path()
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
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


def quota_exhausted_today(provider: str, *, day: str | None = None, path: Path | None = None) -> bool:
    """Whether ``provider`` last told us its allowance is spent, and nothing has succeeded since.

    Scanned in write order so any later evidence of life — an explicit ``quota_retry`` from a resume,
    or simply a call that succeeded and billed tokens — clears the latch. Day-scoped because the
    allowance itself resets at 00:00 UTC.
    """
    dead = False
    for entry in _rows_for_day(day or utc_date(), path):
        if str(entry.get("provider", "")) != provider:
            continue
        kind = entry.get("kind")
        if kind == "quota_exhausted":
            dead = True
        elif kind == "quota_retry" or "prompt_tokens" in entry:
            dead = False
    return dead


def questions_today(identity: str, *, day: str | None = None, path: Path | None = None) -> int:
    """Questions ``identity`` has reserved today against the product cap."""
    total = 0
    for entry in _rows_for_day(day or utc_date(), path):
        if entry.get("kind") != "questions" or str(entry.get("identity", "")) != identity:
            continue
        try:
            total += int(entry["questions"])
        except (KeyError, TypeError, ValueError):
            continue
    return total


def remaining_today(provider: str = "openai", *, path: Path | None = None) -> int:
    """Tokens left in ``provider``'s daily budget by our own count (never negative)."""
    spent = usage_for_day(path=path).get(provider, {}).get("total", 0)
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


def question_cap_reason(identity: str, *, questions: int, path: Path | None = None) -> str | None:
    """Why this identity may not start another Session today, or None (the product cap, AC d).

    Web-only by design, and the reasoning belongs here rather than in a workflow report: the bucket
    is a *token* identity, so it only exists where there is a token to hash. The CLI operator holds
    the provider key and owns the deployment — rationing them against their own allowance would be
    theatre, and the daily-budget and per-run rails already bound what they can spend by accident.
    When real accounts land (R-29) ``identity`` becomes per-user and this moves with them.
    """
    cap = daily_question_cap()
    already = questions_today(identity, path=path)
    if already + questions <= cap:
        return None
    return (
        f"Daily question cap reached: {already} of {cap} question(s) already started today and this "
        f"Session asks for {questions} more. {daily_reset_hint()} Raise COACH_DAILY_QUESTION_CAP to "
        "lift the cap."
    )


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
    if quota_exhausted_today(provider, path=path):
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
    if quota_exhausted_today(provider, path=path):
        clear_quota_exhausted(provider, path=path)
        notes.append(f"retrying {provider} after an insufficient_quota stop")
    if not notes:
        return None
    return "; ".join(notes)
