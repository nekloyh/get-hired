"""Client-side daily token ledger — the only workable free-tier budget rail.

The OpenAI free daily allowance for gpt-5.4-mini (2.5M tokens/day) is NOT exposed by the API:
rate-limit headers carry only the per-minute window (200k TPM / 500 RPM, probed 2026-07-11), so
what remains of the day's budget can only be known by counting what we spent. Every provider call
appends one JSONL line here (from the response's ``usage`` field); the bench and forge print the
day's spend so a long run is never started blind into a dead quota.

R-25 adds the two rails a *product* needs on top of the day counter: a **per-Session** token budget
(nothing bounded a single Session before — a retry storm or a raised ``--max-questions`` could eat
the whole day) and a questions/day cap per token identity. The Session-behaviour half of those rails
is ADR 0005's third category, **budget exhaustion → suspend-and-resume**, and it deliberately lives
in the Session drivers rather than in the graph: a stop raised outside ``question_node`` can never
be caught by its ``except Exception`` net and turned into a zero-evidence ``failed`` question, which
is precisely the fake-evidence corruption that ADR forbids.

Append-only JSONL under ``logs/`` (already gitignored runtime state), tolerant of malformed lines.
Rows are of two kinds: token rows (``prompt_tokens``/``completion_tokens``, optionally attributed to
a ``session``) and question rows (``kind: "questions"``). The readers ignore rows of the other kind
by construction — the token reader already skipped any row missing ``prompt_tokens`` — so the two
share one file without either needing to know about the other.

Recording must NEVER take down a live call — a lost ledger line is noise, a crashed judgment is not.
Days are UTC, matching the provider's daily reset.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

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


# --- R-25 sizing, derived from logs/usage-ledger.jsonl (1,431 rows on main @184f5a2) -------------
#
# Gap-clustered (>10 min) the 1,380 openai/gpt-5.4-mini rows. Five clusters carry the `coach session`
# signature — a ~450p/240c Diagnostic, then repeating [~1,700p evaluator, ~800p, ~850p] triples, then
# a ~1,800p planner call — as opposed to the 455- and 778-call bench sweeps:
#   2026-07-11T13:21  16 calls  26,866 tok
#   2026-07-27T05:12   4 calls   5,596 tok
#   2026-07-27T07:36  11 calls  14,616 tok
#   2026-07-27T12:21   5 calls   6,836 tok
#   2026-07-27T12:42  17 calls  21,891 tok   (1 Diagnostic + 5x3 + 1 planner = a full 5-question run)
#   TOTAL 53 calls / 75,805 tokens  =>  1,430 tokens per provider call.

# The heaviest Session in that set. The start estimate is asserted never to fall below it
# (tests/test_usage.py::test_the_start_estimate_never_underestimates_a_measured_session) — refusing
# to start is free, dying mid-Session is not, so the estimate leans high on purpose.
HEAVIEST_MEASURED_SESSION_TOKENS = 26_866

# Measured Diagnostic calls ranged 681–993 tokens; one Diagnostic runs per Session.
SESSION_SETUP_TOKENS = 1_000
# 26,866 less its 993-token Diagnostic, over 5 questions = 5,175/question, rounded up.
SESSION_TOKENS_PER_QUESTION = 5_200

# Per-Session runaway rail. NOT "2x a typical Session" (~54k): that sits BELOW what a Session's own
# hard rails already permit, so it would suspend a legitimate follow-up-heavy interview, and a rail
# that fires on compliant behaviour is a bug. The worst case max_questions=5 x max_turns=4 allows is
# 1 Diagnostic + 5 x (4 evaluations + 3 panel voices + 3 follow-ups x 2 Interviewer calls + 1
# Supervisor decision) + 1 Study Plan = 72 calls; 72 x 1,430 = 102,960 -> 103,000. So it fires only
# on a genuine runaway (a retry storm, a raised --max-questions), which is what "nothing bounds a
# single Session" asked for. ~3.8x the measured typical Session, 4.1% of the daily allowance.
DEFAULT_SESSION_TOKEN_BUDGET = 103_000

# The daily allowance restated in product units: 2,500,000 / 5,200. Deliberately NOT a small
# per-user number — with one shared secret (R-07) the identity bucket IS the whole deployment, so a
# 10/day default would cap it at two Sessions. The env var is the real product control; this default
# is a backstop that cannot break a shared-token deployment.
DEFAULT_DAILY_QUESTION_CAP = 480


def session_token_budget() -> int:
    return _env_int("LLM_SESSION_TOKEN_BUDGET", DEFAULT_SESSION_TOKEN_BUDGET)


def daily_question_cap() -> int:
    return _env_int("COACH_DAILY_QUESTION_CAP", DEFAULT_DAILY_QUESTION_CAP)


def estimated_session_tokens(n_questions: int, *, include_setup: bool = True) -> int:
    """What a Session of ``n_questions`` is expected to cost, from the measured constants above.

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
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
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
        {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "kind": "questions",
            "identity": identity,
            "questions": int(questions),
        },
        path,
    )


def _append(entry: dict[str, object], path: Path | None) -> None:
    target = path or ledger_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as err:
        logger.warning("usage ledger write failed (%s); dropping entry %s", err, entry)


def _rows_for_day(day: str, path: Path | None) -> Iterator[dict]:
    """Every parseable ledger row stamped ``day``. One corrupt line must not hide the rest."""
    target = path or ledger_path()
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if not str(entry["ts"]).startswith(day):
                continue
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Also the non-dict filter: subscripting a list/str/number raises TypeError here.
            continue
        yield entry


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
            # Also how a question row stays invisible here: it carries no token fields at all.
            continue
        bucket = totals.setdefault(provider, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["total"] += prompt + completion
        bucket["calls"] += 1
    return totals


def sessions_for_day(day: str | None = None, *, path: Path | None = None) -> dict[str, int]:
    """Per-Session token totals for one UTC day. Unattributed rows group under ``""``."""
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
    """Tokens this Session has spent today, across every provider it touched."""
    return sessions_for_day(day, path=path).get(session_id, 0)


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
# Every reason string states the REMEDY as well as the cause. That is the whole difference between a
# suspend (ADR 0005: "suspends with an explicit, user-visible reason and offers resume") and a stall.

_DAILY_RESET_HINT = "The daily allowance resets at 00:00 UTC."


def start_refusal_reason(provider: str, *, questions: int, path: Path | None = None) -> str | None:
    """Why a fresh Session must not start, or None. Checked BEFORE the first token is spent."""
    needed = estimated_session_tokens(questions)
    left = remaining_today(provider, path=path)
    if left >= needed:
        return None
    return (
        f"Not enough of today's {provider} budget left to run a {questions}-question Session: "
        f"~{left:,} tokens remain by our count and this Session is estimated at ~{needed:,}. "
        f"{_DAILY_RESET_HINT} Raise LLM_DAILY_TOKEN_BUDGET if your real allowance is larger, or "
        "start a shorter Session."
    )


def question_cap_reason(identity: str, *, questions: int, path: Path | None = None) -> str | None:
    """Why this identity may not start another Session today, or None (the product cap, AC d)."""
    cap = daily_question_cap()
    already = questions_today(identity, path=path)
    if already + questions <= cap:
        return None
    return (
        f"Daily question cap reached: {already} of {cap} question(s) already started today and this "
        f"Session asks for {questions} more. {_DAILY_RESET_HINT} Raise COACH_DAILY_QUESTION_CAP to "
        "lift the cap."
    )


def budget_stop_reason(
    session_id: str,
    provider: str,
    *,
    questions_left: int,
    path: Path | None = None,
) -> str | None:
    """Why a running Session must suspend now, or None.

    Called by the Session drivers at the graph's node boundary, so a stop is raised OUTSIDE the
    graph and can never be recorded as a ``failed`` question (ADR 0005).
    """
    budget = session_token_budget()
    spent = session_spend(session_id, path=path)
    if spent >= budget:
        return (
            f"Session {session_id!r} has spent ~{spent:,} tokens, past its per-Session budget of "
            f"~{budget:,} (LLM_SESSION_TOKEN_BUDGET). Suspending so the spend cannot run away; the "
            "questions resolved so far are kept. Raise LLM_SESSION_TOKEN_BUDGET, then resume this "
            "Session to continue."
        )
    # A Session with nothing left to ask costs 0 from here, so the comparison below returns None on
    # its own — no separate guard, and no way for this rail to strand a Session one node from its
    # Study Plan.
    needed = estimated_session_tokens(questions_left, include_setup=False)
    left = remaining_today(provider, path=path)
    if left >= needed:
        return None
    return (
        f"Today's {provider} budget cannot fund the {questions_left} question(s) left in this "
        f"Session: ~{left:,} tokens remain by our count and ~{needed:,} are estimated. Suspending "
        f"instead of failing the remaining questions. {_DAILY_RESET_HINT} Resume this Session after "
        "the reset to finish it."
    )
