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
plus a ``_meta: {schema_version}`` key — diff-friendly and hand-inspectable. A missing or corrupt
ledger degrades to cold start with a logged warning; it never crashes a Session.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .filelock import atomic_write_text, locked
from .skill import NEUTRAL_ALPHA, NEUTRAL_BETA, SkillState

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400.0
# Written under the top-level ``_meta`` key; candidate records are every other key.
LEDGER_SCHEMA_VERSION = 1

# A Candidate id is a *key* in one shared JSON file that every pilot Session and both CLI commands
# read and rewrite, so it is constrained the way the Session id already is. This is NOT ownership:
# one shared secret is one principal (`Settings.auth_token`, R-07 — real per-user auth is R-29), so
# no server-side derivation available today can separate two pilot users who share a token. What it
# closes is the free-text half of QA-02: an unbounded, arbitrary-charset key in a file this module
# promises is "diff-friendly and hand-inspectable", and one that `%r` formats straight into a log
# line. Note it refuses diacritics, so a Vietnamese name is an invalid KEY — the field is an id, and
# the UI says so; widening to Unicode letters re-opens the log-forging and hand-editability
# arguments and should be a deliberate decision, not a loosening to make a test pass.
# The leading `_` is reserved for this module's own keys (`_meta`), so a Candidate id can never
# collide with one — NEW-28: `_meta` matched the old rule, so a Candidate using it persisted and
# warm-started correctly and was then silently destroyed by the next Candidate's save. The whole
# prefix rather than the one literal, because the next metadata key would reopen it. It must stay a
# CHARACTER CLASS: web_api feeds this pattern straight into a pydantic `Field(pattern=...)` and
# pydantic's rust-regex engine has no look-around, so a negative lookahead fails at import.
SAFE_CANDIDATE_ID = re.compile(r"[A-Za-z0-9-][A-Za-z0-9_-]{0,63}")


def is_safe_candidate_id(candidate_id: str) -> bool:
    """Whether ``candidate_id`` may be used as a Skill ledger key."""
    return bool(SAFE_CANDIDATE_ID.fullmatch(candidate_id))

# Half-life of carried evidence, in days: after this long a Skill's pseudo-count mass above the neutral
# prior has decayed by half, so a returning Candidate's edge fades over ~a month of absence. Chosen so
# a next-day return keeps almost all of last Session's signal while a months-later return is nearly a
# cold start — honest epistemics without a hard cliff.
LEDGER_HALF_LIFE_DAYS = 30.0

# Serialises the whole load-modify-save in `save_posteriors`. The web API runs every Session on its
# own thread and saves posteriors when it completes, so two Candidates finishing together race the
# same file: without this, the later writer merges into a stale read and silently drops the earlier
# Candidate's record — infrastructure noise corrupting Skill evidence, which ADR 0005 forbids.
# A process-local Lock is not enough on its own, and the old "the server is documented
# single-process" argument (docs/deploy.md §6) never covered the case that breaks it: `coach session`
# and `coach postmortem` write this same file from a SECOND OS process. So the merge also takes an
# advisory flock on a `.lock` sidecar — thread lock OUTER, file lock inner, because flock is held per
# open file description and two threads of one process each open their own, so the reverse order is a
# lock-order inversion that deadlocks them against each other. Readers deliberately take neither:
# publication is an atomic
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


def _ledger_version_is_supported(data: Mapping[str, Any], path: object) -> bool:
    """The one reader of ``LEDGER_SCHEMA_VERSION`` (docs/data-model.md §4). Never raises.

    Refuse higher, tolerate lower — the same rule as the checkpoint's reader, but expressed as a bool
    because both loaders and ``save_posteriors`` are contractually forbidden to raise. The
    load-bearing half is the WRITE refusal: without it an old build handed a v2 ledger rewrites it on
    the next completion, stamping ``_meta`` back down and clobbering whatever the newer shape held.
    Declining to save costs one Session's cross-session memory, which ADR 0006 already tolerates as a
    cold start; downgrading the file costs every Candidate in it, permanently.
    """
    meta = data.get("_meta")
    version = meta.get("schema_version", 0) if isinstance(meta, Mapping) else 0
    if isinstance(version, bool) or not isinstance(version, int) or version > LEDGER_SCHEMA_VERSION:
        logger.error(
            "Skill ledger at %s carries schema_version %r; this build understands up to %d. "
            "Refusing to read or overwrite it.",
            path,
            version,
            LEDGER_SCHEMA_VERSION,
        )
        return False
    return True


def _load_candidate(
    path: str | Path, candidate_id: str, now: float
) -> tuple[float, dict[str, tuple[float, float]]] | None:
    """Read and validate one Candidate's record: ``(days_elapsed, {skill: (alpha, beta)})`` or ``None``.

    Never raises: a missing file or unknown Candidate is a normal cold start; a corrupt, malformed or
    non-finite ledger logs a warning and degrades to cold start rather than crashing the Session.
    """
    if not candidate_id:
        return None
    if not is_safe_candidate_id(candidate_id):
        logger.warning("%r is not a valid Skill ledger key; starting cold.", candidate_id)
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as err:
        logger.warning("Skill ledger unreadable at %s (%s); starting cold.", path, err)
        return None
    try:
        payload = json.loads(raw)
        if isinstance(payload, Mapping) and not _ledger_version_is_supported(payload, path):
            return None
        entry = payload[candidate_id]
        completed_at = float(entry["completed_at"])
        if not math.isfinite(completed_at):
            raise ValueError("non-finite completed_at")
        days_elapsed = max(0.0, (now - completed_at) / SECONDS_PER_DAY)
        params: dict[str, tuple[float, float]] = {}
        for skill, raw_params in entry["skills"].items():
            alpha = float(raw_params["alpha"])
            beta = float(raw_params["beta"])
            # json.loads accepts NaN/Infinity, and every comparison against NaN is False, so the
            # positivity check alone would let a non-finite param through. Reject it explicitly.
            if not (math.isfinite(alpha) and math.isfinite(beta)) or alpha <= 0 or beta <= 0:
                raise ValueError(f"invalid Beta params for {skill!r} (must be finite and positive)")
            params[skill] = (alpha, beta)
    except KeyError:
        # File exists but has no record for this Candidate — a normal first-ever Session for them.
        return None
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        logger.warning("Skill ledger for %r is malformed (%s); starting cold.", candidate_id, err)
        return None
    return (days_elapsed, params) if params else None


def load_priors(path: str | Path, candidate_id: str, *, now: float) -> LedgerPriors | None:
    """Load a Candidate's carried priors, or ``None`` for a first-ever/absent/corrupt ledger."""
    loaded = _load_candidate(path, candidate_id, now)
    if loaded is None:
        return None
    days_elapsed, params = loaded
    raw_mastery: dict[str, float] = {}
    seed_means: dict[str, float] = {}
    for skill, (alpha, beta) in params.items():
        raw_mastery[skill] = alpha / (alpha + beta)
        d_alpha, d_beta = decay_beta(alpha, beta, days_elapsed)
        seed_means[skill] = d_alpha / (d_alpha + d_beta)
    return LedgerPriors(raw_mastery=raw_mastery, seed_means=seed_means, days_elapsed=days_elapsed)


def load_states(path: str | Path, candidate_id: str, *, now: float) -> dict[str, SkillState] | None:
    """Load a Candidate's full decayed Beta params as SkillStates (issue 0026), or ``None``.

    Unlike :func:`load_priors` this keeps both parameters, so reconstructed post-mortem evidence
    can be fused through the sanctioned ``observe()`` seam. Decay is applied HERE, before any caller
    observes new evidence: ``save_posteriors`` stamps a fresh ``completed_at`` for the whole record,
    so saving un-decayed params back would silently un-decay stale evidence.
    """
    loaded = _load_candidate(path, candidate_id, now)
    if loaded is None:
        return None
    days_elapsed, params = loaded
    states: dict[str, SkillState] = {}
    for skill, (alpha, beta) in params.items():
        d_alpha, d_beta = decay_beta(alpha, beta, days_elapsed)
        states[skill] = SkillState(skill=skill, alpha=d_alpha, beta=d_beta)
    return states


def save_posteriors(
    path: str | Path,
    candidate_id: str,
    skill_states: Mapping[str, SkillState],
    *,
    now: float,
) -> None:
    """Persist a Candidate's final per-Skill posteriors, merging into any existing ledger.

    The merge is serialised under ``_SAVE_LOCK`` *and* an inter-process flock, and published by
    atomic rename, so concurrent completions — another thread here, or a concurrent ``coach
    postmortem`` — cannot lose each other's records, and a save that dies mid-flight leaves the
    previous ledger intact rather than a truncated file that cold-starts every Candidate in it.

    Never raises on a write problem: failing to record memory must not fail an otherwise-complete
    Session — it logs a warning and moves on.
    """
    if not candidate_id:
        return
    if not is_safe_candidate_id(candidate_id):
        logger.warning("%r is not a valid Skill ledger key; Session memory not persisted.", candidate_id)
        return
    target = Path(path)
    with _SAVE_LOCK, locked(target):
        data: dict[str, object] = {}
        try:
            if target.exists():
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
            # UnicodeDecodeError is a ValueError, not an OSError, so it used to walk out of a
            # function whose docstring promises it never raises. NOTE this inherits the existing
            # "unreadable -> overwrite" policy: one corrupt byte discards every other Candidate's
            # record. That is the pre-existing policy for malformed JSON and is deliberately not
            # changed here; quarantine-instead-of-overwrite deserves its own finding.
            logger.warning("Skill ledger at %s unreadable before save (%s); overwriting.", path, err)
        if not _ledger_version_is_supported(data, target):
            return  # never downgrade a ledger a newer build wrote
        data["_meta"] = {"schema_version": LEDGER_SCHEMA_VERSION}
        data[candidate_id] = {
            "completed_at": now,
            "skills": {skill: {"alpha": state.alpha, "beta": state.beta} for skill, state in skill_states.items()},
        }
        try:
            # Shared with the Markdown export (NEW-04): both live on the same /state volume and both
            # must survive a disk that fills mid-write. This function is contractually forbidden to
            # raise, so the OSError stops here.
            atomic_write_text(target, json.dumps(data, indent=2, sort_keys=True))
        except OSError as err:
            logger.warning("Could not write Skill ledger at %s (%s); Session memory not persisted.", path, err)


def save_measured_posteriors(
    path: str | Path,
    candidate_id: str,
    measured: Mapping[str, SkillState],
    *,
    now: float,
) -> None:
    """Persist a Session's MEASURED posteriors without erasing what earlier Sessions measured.

    ``save_posteriors`` replaces a Candidate's whole record, so handing it only this Session's probed
    Skills would drop every Skill measured in an earlier one — trading a fake-evidence bug for a
    lost-evidence bug. Carrying ``load_states`` forward first is the same decay-before-observe
    composition the post-mortem already uses: the carried params are decayed to ``now`` BEFORE the
    save restamps the record's decay clock, so nothing is silently un-decayed.
    """
    carried = load_states(path, candidate_id, now=now) or {}
    save_posteriors(path, candidate_id, {**carried, **measured}, now=now)
