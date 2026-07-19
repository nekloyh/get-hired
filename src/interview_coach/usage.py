"""Client-side daily token ledger — the only workable free-tier budget rail.

The OpenAI free daily allowance for gpt-5.4-mini (2.5M tokens/day) is NOT exposed by the API:
rate-limit headers carry only the per-minute window (200k TPM / 500 RPM, probed 2026-07-11), so
what remains of the day's budget can only be known by counting what we spent. Every provider call
appends one JSONL line here (from the response's ``usage`` field); the bench and forge print the
day's spend so a long run is never started blind into a dead quota.

Append-only JSONL under ``logs/`` (already gitignored runtime state), tolerant of malformed lines.
Recording must NEVER take down a live call — a lost ledger line is noise, a crashed judgment is not.
Days are UTC, matching the provider's daily reset.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
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


def daily_token_budget() -> int:
    raw = os.environ.get("LLM_DAILY_TOKEN_BUDGET", "")
    try:
        return int(raw) if raw else DEFAULT_DAILY_TOKEN_BUDGET
    except ValueError:
        logger.warning("LLM_DAILY_TOKEN_BUDGET=%r is not an integer; using default %d", raw, DEFAULT_DAILY_TOKEN_BUDGET)
        return DEFAULT_DAILY_TOKEN_BUDGET


def record_usage(
    provider: str,
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    path: Path | None = None,
) -> None:
    """Append one call's token usage to the ledger. Swallows IO errors by design."""
    entry = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
    }
    target = path or ledger_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as err:
        logger.warning("usage ledger write failed (%s); dropping entry %s", err, entry)


def usage_for_day(day: str | None = None, *, path: Path | None = None) -> dict[str, dict[str, int]]:
    """Per-provider token totals for one UTC day (default: today).

    Returns ``{provider: {"prompt": ..., "completion": ..., "total": ..., "calls": ...}}``.
    Malformed lines are skipped: the ledger is advisory, and one corrupt line must not hide the
    rest of the day's spend.
    """
    target = path or ledger_path()
    day = day or utc_date()
    totals: dict[str, dict[str, int]] = {}
    if not target.exists():
        return totals
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if not str(entry["ts"]).startswith(day):
                continue
            prompt, completion = int(entry["prompt_tokens"]), int(entry["completion_tokens"])
            provider = str(entry["provider"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        bucket = totals.setdefault(provider, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["total"] += prompt + completion
        bucket["calls"] += 1
    return totals


def remaining_today(provider: str = "openai", *, path: Path | None = None) -> int:
    """Tokens left in ``provider``'s daily budget by our own count (never negative)."""
    spent = usage_for_day(path=path).get(provider, {}).get("total", 0)
    return max(0, daily_token_budget() - spent)
