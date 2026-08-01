"""Per-Candidate cross-session memory as decayed Bayesian priors (ADR 0006).

When a Session completes we persist the final per-Skill Beta posteriors for a Candidate id; when the
same Candidate returns we re-seed the next Session's priors from them, with exponential pseudo-count
decay by days elapsed. This is deliberately no-LLM, offline-testable arithmetic (ADR 0006): old
evidence is weaker evidence, so a Candidate who was strong months ago starts *warmer than a stranger
but is still probed*. We do not retrieve past transcripts into prompts.

The ledger only supplies the prior *mean* fed through the Diagnostic's existing seam
(``diagnostic._initial_mastery_means``); Role criticality still sets prior *strength* and the
evidence bar (ADR 0002 — role never moves the mean, and the seeded prior stays weak enough that fresh
direct evidence dominates within an answer or two).

Storage is a single JSON file mapping ``candidate_id -> {completed_at, skills: {skill: {alpha, beta}}}``
— diff-friendly and hand-inspectable. A missing or corrupt ledger degrades to cold start with a
logged warning; it never crashes a Session.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .skill import NEUTRAL_ALPHA, NEUTRAL_BETA, SkillState

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400.0

# Half-life of carried evidence, in days: after this long a Skill's pseudo-count mass above the neutral
# prior has decayed by half, so a returning Candidate's edge fades over ~a month of absence. Chosen so
# a next-day return keeps almost all of last Session's signal while a months-later return is nearly a
# cold start — honest epistemics without a hard cliff.
LEDGER_HALF_LIFE_DAYS = 30.0

# Serialises the whole load-modify-save in `save_posteriors`. The web API runs every Session on its
# own thread and saves posteriors when it completes, so two Candidates finishing together race the
# same file: without this, the later writer merges into a stale read and silently drops the earlier
# Candidate's record — infrastructure noise corrupting Skill evidence, which ADR 0005 forbids.
# A process-local Lock suffices only because the server is documented single-process (docs/deploy.md
# §6 "Do not add workers"; R-12/#67 adds the guard that enforces it). Multi-process — R-29's Postgres
# store — needs real locking, not this. Readers deliberately do NOT take it: publication is an atomic
# rename, so a reader sees the whole old file or the whole new one, and holding it on the hot
# start-of-Session path would only add contention plus a deadlock surface (`postmortem` already
# chains load_states → save_posteriors around it).
_SAVE_LOCK = threading.Lock()


def decay_beta(
    alpha: float,
    beta: float,
    days_elapsed: float,
    *,
    half_life_days: float = LEDGER_HALF_LIFE_DAYS,
) -> tuple[float, float]:
    """Decay a Beta(α, β) toward the neutral prior by ``days_elapsed`` (exponential pseudo-counts).

    The pseudo-count mass *above* the neutral prior shrinks by ``0.5 ** (days / half_life)``: at 0 days
    nothing decays, at one half-life half the accumulated evidence is gone, and as days → ∞ the state
    returns to the weak neutral prior (mean 0.5). Because the neutral prior is symmetric this both
    lowers confidence and pulls the mean back toward 0.5 — so older evidence counts strictly less.
    """
    if days_elapsed < 0:
        days_elapsed = 0.0
    factor = math.exp(-math.log(2.0) * days_elapsed / half_life_days)
    decayed_alpha = NEUTRAL_ALPHA + (alpha - NEUTRAL_ALPHA) * factor
    decayed_beta = NEUTRAL_BETA + (beta - NEUTRAL_BETA) * factor
    return decayed_alpha, decayed_beta


@dataclass(frozen=True)
class LedgerPriors:
    """A returning Candidate's carried priors, ready to seed the next Session."""

    raw_mastery: dict[str, float]  # last Session's per-Skill mean, for the "since last session" display
    seed_means: dict[str, float]  # decayed mean fed to the Diagnostic prior seam
    days_elapsed: float


def load_priors(path: str | Path, candidate_id: str, *, now: float) -> LedgerPriors | None:
    """Load a Candidate's carried priors, or ``None`` for a first-ever/absent/corrupt ledger.

    Never raises: a missing file is a normal cold start; a corrupt or malformed ledger logs a warning
    and degrades to cold start rather than crashing the Session.
    """
    if not candidate_id:
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as err:
        logger.warning("Skill ledger unreadable at %s (%s); starting cold.", path, err)
        return None
    try:
        data = json.loads(raw)
        entry = data[candidate_id]
        completed_at = float(entry["completed_at"])
        if not math.isfinite(completed_at):
            raise ValueError("non-finite completed_at")
        skills = entry["skills"]
        raw_mastery: dict[str, float] = {}
        seed_means: dict[str, float] = {}
        days_elapsed = max(0.0, (now - completed_at) / SECONDS_PER_DAY)
        for skill, params in skills.items():
            alpha = float(params["alpha"])
            beta = float(params["beta"])
            # json.loads accepts NaN/Infinity, and every comparison against NaN is False, so the
            # positivity check alone would let a non-finite param through into NaN seed priors —
            # exactly the outcome this module promises is impossible. Reject non-finite explicitly.
            if not (math.isfinite(alpha) and math.isfinite(beta)) or alpha <= 0 or beta <= 0:
                raise ValueError(f"invalid Beta params for {skill!r} (must be finite and positive)")
            raw_mastery[skill] = alpha / (alpha + beta)
            d_alpha, d_beta = decay_beta(alpha, beta, days_elapsed)
            seed_means[skill] = d_alpha / (d_alpha + d_beta)
    except KeyError:
        # File exists but has no record for this Candidate — a normal first-ever Session for them.
        return None
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        logger.warning("Skill ledger for %r is malformed (%s); starting cold.", candidate_id, err)
        return None
    if not seed_means:
        return None
    return LedgerPriors(raw_mastery=raw_mastery, seed_means=seed_means, days_elapsed=days_elapsed)


def load_states(path: str | Path, candidate_id: str, *, now: float) -> dict[str, SkillState] | None:
    """Load a Candidate's per-Skill Beta posteriors, decayed to ``now`` (issue 0026).

    Unlike :func:`load_priors` — which deliberately exposes only *means* for the Diagnostic prior
    seam — this rehydrates full :class:`SkillState` objects so reconstructed post-mortem evidence
    can be fused through the sanctioned ``observe()`` seam. Decay is applied HERE, before any caller
    observes new evidence: ``save_posteriors`` stamps a fresh ``completed_at`` for the whole record,
    so saving un-decayed params back would silently un-decay stale evidence.

    Never raises: missing/unknown/corrupt/non-finite ledgers degrade to ``None`` (cold start) with
    the same discipline as :func:`load_priors`.
    """
    if not candidate_id:
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as err:
        logger.warning("Skill ledger unreadable at %s (%s); starting cold.", path, err)
        return None
    try:
        data = json.loads(raw)
        entry = data[candidate_id]
        completed_at = float(entry["completed_at"])
        if not math.isfinite(completed_at):
            raise ValueError("non-finite completed_at")
        days_elapsed = max(0.0, (now - completed_at) / SECONDS_PER_DAY)
        states: dict[str, SkillState] = {}
        for skill, params in entry["skills"].items():
            alpha = float(params["alpha"])
            beta = float(params["beta"])
            # Same explicit non-finite rejection as load_priors: json.loads accepts NaN/Infinity and
            # NaN defeats every comparison, so the positivity check alone is not enough.
            if not (math.isfinite(alpha) and math.isfinite(beta)) or alpha <= 0 or beta <= 0:
                raise ValueError(f"invalid Beta params for {skill!r} (must be finite and positive)")
            d_alpha, d_beta = decay_beta(alpha, beta, days_elapsed)
            states[skill] = SkillState(skill=skill, alpha=d_alpha, beta=d_beta)
    except KeyError:
        # File exists but has no record for this Candidate — a normal first-ever post-mortem for them.
        return None
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        logger.warning("Skill ledger for %r is malformed (%s); starting cold.", candidate_id, err)
        return None
    return states or None


def save_posteriors(
    path: str | Path,
    candidate_id: str,
    skill_states: Mapping[str, SkillState],
    *,
    now: float,
) -> None:
    """Persist a Candidate's final per-Skill posteriors, merging into any existing ledger.

    The merge is serialised under ``_SAVE_LOCK`` and published by atomic rename, so concurrent
    completions cannot lose each other's records and a save that dies mid-flight leaves the previous
    ledger intact rather than a truncated file that cold-starts every Candidate in it.

    Never raises on a write problem: failing to record memory must not fail an otherwise-complete
    Session — it logs a warning and moves on.
    """
    if not candidate_id:
        return
    target = Path(path)
    with _SAVE_LOCK:
        data: dict[str, object] = {}
        try:
            if target.exists():
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
        except (OSError, json.JSONDecodeError) as err:
            logger.warning("Skill ledger at %s unreadable before save (%s); overwriting.", path, err)
        data[candidate_id] = {
            "completed_at": now,
            "skills": {
                skill: {"alpha": state.alpha, "beta": state.beta}
                for skill, state in skill_states.items()
            },
        }
        tmp_path: Path | None = None
        try:
            # The tempfile must be a sibling of the target: os.replace is only atomic within one
            # filesystem and raises EXDEV across a mount boundary (the Docker /state volume is one).
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)  # bound first, so a failed write still gets cleaned up
                handle.write(json.dumps(data, indent=2, sort_keys=True))
                handle.flush()
                # Rename is atomic w.r.t. readers but says nothing about durability: without fsync a
                # container restart can publish a name pointing at unflushed (zero) bytes.
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except OSError as err:
            # This handler is inside a function contractually forbidden to raise, so the cleanup must
            # not become what escapes it — hence suppress rather than a second bare unlink.
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
            logger.warning("Could not write Skill ledger at %s (%s); Session memory not persisted.", path, err)
