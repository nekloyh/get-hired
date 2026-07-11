"""Process-local counters for structural-noise and transport events (free-tier hardening).

The judge's structural-noise folds (the Evaluation sanitizer), structured-output retries, and
transport backoffs were previously visible only as scattered log lines, so a NEW noise mode from
the live model first showed up as a red bench with no warning (the 24/29 day). These counters make
noise drift measurable: the bench snapshots them around a run and prints the delta, so a new fold
pattern surfaces as a counter moving while the run is still green.

Deliberately minimal: one module-level Counter behind four functions, single-threaded like the CLI.
Not persisted — persistence belongs to the usage ledger (usage.py), which tracks spend, not noise.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

_counters: Counter[str] = Counter()


def incr(key: str, n: int = 1) -> None:
    """Count ``n`` occurrences of a named event (e.g. ``'sanitizer.judgment_flattened'``)."""
    _counters[key] += n


def snapshot() -> dict[str, int]:
    """The current counts as a plain dict — safe to hold and diff against a later snapshot."""
    return dict(_counters)


def reset() -> None:
    _counters.clear()


def delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    """Counts that moved between two snapshots — what one bench/forge run actually folded."""
    return {key: count - before.get(key, 0) for key, count in after.items() if count != before.get(key, 0)}
