from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from interview_coach.diagnostic import CandidateProfile, diagnose
from interview_coach.evaluator import Evaluation
from interview_coach.ledger import (
    LEDGER_HALF_LIFE_DAYS,
    SECONDS_PER_DAY,
    decay_beta,
    load_priors,
    load_states,
    save_posteriors,
)
from interview_coach.skill import NEUTRAL_ALPHA, NEUTRAL_BETA, SkillState, apply_evaluation

DAY = SECONDS_PER_DAY


def _evaluation(weighted_score: float) -> Evaluation:
    return Evaluation(
        dimensions={},
        weighted_score=weighted_score,
        confidence=0.9,
        follow_up_recommended=False,
        follow_up_rationale="n/a",
    )


def _mean(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta)


# --- decay math ---------------------------------------------------------------------------------


def test_decay_is_identity_at_zero_days():
    assert decay_beta(8.0, 2.0, 0.0) == pytest.approx((8.0, 2.0))


def test_decay_halves_evidence_mass_at_one_half_life():
    alpha, beta = decay_beta(9.0, 1.0, LEDGER_HALF_LIFE_DAYS)
    # Mass above the neutral prior halves: (9-1)->4 over neutral 1, (1-1)->0 over neutral 1.
    assert alpha == pytest.approx(NEUTRAL_ALPHA + (9.0 - NEUTRAL_ALPHA) * 0.5)
    assert beta == pytest.approx(NEUTRAL_BETA + (1.0 - NEUTRAL_BETA) * 0.5)


def test_older_evidence_counts_strictly_less():
    # A strong posterior decays toward the neutral mean (0.5); more elapsed time ⇒ strictly closer to 0.5.
    near = _mean(*decay_beta(8.0, 2.0, 5.0))
    far = _mean(*decay_beta(8.0, 2.0, 60.0))
    assert 0.5 < far < near < 0.8  # both above neutral, but the older one is pulled harder toward 0.5


def test_decay_approaches_neutral_over_long_absence():
    alpha, beta = decay_beta(8.0, 2.0, 3650.0)  # ~10 years
    assert _mean(alpha, beta) == pytest.approx(0.5, abs=1e-3)


# --- persistence + robustness -------------------------------------------------------------------


def test_save_then_load_round_trips_raw_mastery(tmp_path):
    path = tmp_path / "ledger.json"
    states = {
        "mlops": SkillState("mlops", alpha=8.0, beta=2.0),
        "deep_learning": SkillState("deep_learning", alpha=3.0, beta=3.0),
    }
    save_posteriors(path, "alice", states, now=1000.0)

    priors = load_priors(path, "alice", now=1000.0)  # same instant ⇒ no decay
    assert priors is not None
    assert priors.raw_mastery["mlops"] == pytest.approx(0.8)
    assert priors.seed_means["mlops"] == pytest.approx(0.8)  # zero days elapsed
    assert priors.days_elapsed == pytest.approx(0.0)


def test_load_decays_seed_means_by_elapsed_days(tmp_path):
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)

    priors = load_priors(path, "alice", now=90.0 * DAY)
    assert priors is not None
    assert priors.raw_mastery["mlops"] == pytest.approx(0.8)  # display value is un-decayed
    assert 0.5 < priors.seed_means["mlops"] < 0.8  # seeded value is decayed toward neutral


def test_save_merges_multiple_candidates(tmp_path):
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    save_posteriors(path, "bob", {"mlops": SkillState("mlops", alpha=2.0, beta=8.0)}, now=0.0)

    assert load_priors(path, "alice", now=0.0).raw_mastery["mlops"] == pytest.approx(0.8)
    assert load_priors(path, "bob", now=0.0).raw_mastery["mlops"] == pytest.approx(0.2)


def test_missing_ledger_is_cold_start(tmp_path):
    assert load_priors(tmp_path / "nope.json", "alice", now=0.0) is None


def test_empty_candidate_id_never_loads_or_saves(tmp_path):
    path = tmp_path / "ledger.json"
    save_posteriors(path, "", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    assert not path.exists()
    assert load_priors(path, "", now=0.0) is None


def test_unknown_candidate_is_cold_start(tmp_path):
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    assert load_priors(path, "stranger", now=0.0) is None


def test_corrupt_ledger_degrades_to_cold_start_without_crashing(tmp_path, caplog):
    path = tmp_path / "ledger.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_priors(path, "alice", now=0.0) is None


def test_malformed_entry_degrades_to_cold_start(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"alice": {"completed_at": 0.0, "skills": {"mlops": {"alpha": -1}}}}), encoding="utf-8")
    assert load_priors(path, "alice", now=0.0) is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_beta_params_degrade_to_cold_start_not_nan_priors(tmp_path, bad):
    # json.loads accepts NaN/Infinity, and every comparison against NaN is False, so a naive
    # `alpha <= 0` guard would let a non-finite param through into NaN seed priors — the exact
    # outcome the module promises is impossible. It must degrade to cold start instead.
    path = tmp_path / "ledger.json"
    path.write_text(
        f'{{"alice": {{"completed_at": 0.0, "skills": {{"mlops": {{"alpha": {bad}, "beta": 1.0}}}}}}}}',
        encoding="utf-8",
    )
    assert load_priors(path, "alice", now=0.0) is None


def test_non_finite_completed_at_degrades_to_cold_start(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        '{"alice": {"completed_at": NaN, "skills": {"mlops": {"alpha": 2.0, "beta": 1.0}}}}',
        encoding="utf-8",
    )
    assert load_priors(path, "alice", now=0.0) is None


# --- load_states: full decayed Beta params for the post-mortem fusion (issue 0026) ---------------


def test_load_states_returns_decayed_beta_params(tmp_path):
    # Unlike load_priors (means only), load_states rehydrates SkillStates — already decayed, so a
    # caller observing new evidence cannot silently un-decay stale mass when save_posteriors
    # restamps completed_at.
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=9.0, beta=1.0)}, now=0.0)

    states = load_states(path, "alice", now=LEDGER_HALF_LIFE_DAYS * DAY)

    assert states["mlops"].alpha == pytest.approx(NEUTRAL_ALPHA + (9.0 - NEUTRAL_ALPHA) * 0.5)
    assert states["mlops"].beta == pytest.approx(NEUTRAL_BETA + (1.0 - NEUTRAL_BETA) * 0.5)


def test_load_states_missing_unknown_or_empty_candidate_is_cold_start(tmp_path):
    path = tmp_path / "ledger.json"
    assert load_states(path, "alice", now=0.0) is None  # missing file
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    assert load_states(path, "stranger", now=0.0) is None  # unknown Candidate
    assert load_states(path, "", now=0.0) is None  # empty id no-ops


def test_load_states_corrupt_or_non_finite_degrades_to_cold_start(tmp_path):
    # Same never-raise / isfinite discipline as load_priors: a broken ledger is a cold start,
    # never a crash and never NaN Beta params.
    path = tmp_path / "ledger.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_states(path, "alice", now=0.0) is None
    path.write_text(
        '{"alice": {"completed_at": 0.0, "skills": {"mlops": {"alpha": NaN, "beta": 1.0}}}}',
        encoding="utf-8",
    )
    assert load_states(path, "alice", now=0.0) is None


# --- atomic publish + save serialisation (R-10) -------------------------------------------------


def test_concurrent_saves_for_different_candidates_both_persist(tmp_path, monkeypatch):
    # The web API runs every Session on its own thread and saves posteriors when it completes, so two
    # Candidates finishing together hit this function concurrently. A bare read-modify-write loses
    # whichever record was read before the other thread's write landed — infrastructure noise erasing
    # a Candidate's Skill evidence, which ADR 0005 forbids. Widening the read→write window with a
    # sleep makes the race deterministic rather than GIL-dependent (a naive two-thread test passes on
    # the broken code by luck); under the lock thread B just waits, so this stays ~0.1s.
    path = tmp_path / "ledger.json"
    save_posteriors(path, "carol", {"mlops": SkillState("mlops", alpha=4.0, beta=4.0)}, now=0.0)

    real_read_text = Path.read_text

    def slow_read_text(self, *args, **kwargs):
        raw = real_read_text(self, *args, **kwargs)
        if self == path:
            time.sleep(0.05)
        return raw

    monkeypatch.setattr(Path, "read_text", slow_read_text)
    barrier = threading.Barrier(2)  # outside the critical section — inside it, the lock would deadlock

    def save(candidate_id: str, alpha: float, beta: float) -> None:
        barrier.wait()
        states = {"mlops": SkillState("mlops", alpha=alpha, beta=beta)}
        save_posteriors(path, candidate_id, states, now=0.0)

    threads = [
        threading.Thread(target=save, args=("alice", 9.0, 1.0)),
        threading.Thread(target=save, args=("bob", 2.0, 1.0)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    monkeypatch.undo()

    # Both new records AND the pre-existing one survive the merge — losing "carol" would mean the
    # winning writer had merged into a stale read.
    assert sorted(json.loads(path.read_text(encoding="utf-8"))) == ["alice", "bob", "carol"]
    assert load_priors(path, "alice", now=0.0).raw_mastery["mlops"] == pytest.approx(0.9)
    assert load_priors(path, "bob", now=0.0).raw_mastery["mlops"] == pytest.approx(2.0 / 3.0)


def test_failed_publish_keeps_the_old_ledger_and_leaves_no_temp_file(tmp_path, monkeypatch, caplog):
    # The never-raise contract, sharpened: a truncating write that dies mid-flight leaves a half file
    # that every later load reads as malformed, cold-starting every Candidate in it. Publishing by
    # rename means a failed save is a no-op — the previous ledger is still there, byte-identical —
    # and the abandoned tempfile must not accumulate one-per-Session on a failing disk.
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    before = path.read_bytes()

    published_from = []

    def exploding_replace(src, dst, *args, **kwargs):
        published_from.append(Path(src))
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", exploding_replace)
    save_posteriors(path, "bob", {"mlops": SkillState("mlops", alpha=2.0, beta=8.0)}, now=0.0)

    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ledger.json"]
    assert "not persisted" in caplog.text
    # The staged file has to be a sibling of the target, not somewhere under the system temp dir:
    # os.replace is only atomic within a single filesystem and raises EXDEV across a mount boundary,
    # which is exactly what the Docker /state volume is.
    assert published_from and published_from[0].parent == tmp_path


# --- two-session invariant (ADR 0002 / 0006) ----------------------------------------------------


def test_ledger_warms_the_prior_but_fresh_evidence_still_dominates(tmp_path):
    path = tmp_path / "ledger.json"
    profile = CandidateProfile(target_role="machine learning engineer")

    # First-ever Session behaves exactly as cold start.
    cold = diagnose(profile, None)
    cold_mlops = cold.priors["mlops"].state.mastery
    assert cold_mlops == pytest.approx(0.5, abs=0.05)

    # Session 1 leaves a strong mlops posterior; the next Session starts warm.
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    carried = load_priors(path, "alice", now=0.0)
    warm = diagnose(profile, None, ledger_priors=carried.seed_means)
    warm_mlops_state = warm.priors["mlops"].state
    assert warm_mlops_state.mastery > cold_mlops + 0.2  # carryover: the prior mean is warmer

    # ADR 0002 invariant: two weak answers overwhelm the carried prior — fresh evidence dominates.
    after = apply_evaluation(apply_evaluation(warm_mlops_state, _evaluation(1)), _evaluation(1))
    assert after.mastery < 0.5


def test_export_shows_since_last_session_delta_only_for_a_returning_candidate():
    from interview_coach.exporter import render_session_markdown

    base = {
        "session_id": "s1",
        "status": "complete",
        "skill_states": {"mlops": {"skill": "mlops", "alpha": 6.0, "beta": 2.0}},  # mastery 0.75
    }
    # Cold start: no ledger prior stashed ⇒ no delta block.
    assert "Since Previous Session" not in render_session_markdown(base)

    # Returning Candidate: the before → after block appears.
    returning = {**base, "ledger_prior_mastery": {"mlops": 0.40}}
    report = render_session_markdown(returning)
    assert "Since Previous Session" in report
    assert "0.400" in report and "0.750" in report and "+0.350" in report


def test_export_shows_llm_calls_per_turn_with_the_provider_split():
    # R-26 DoD: the export is where a finished session's cost and routing become reviewable. The
    # provider split is the part that matters — a judge turn whose calls landed on a provider the
    # role was never pinned to is the ADR 0009 silent failover, invisible everywhere else.
    from interview_coach.exporter import render_session_markdown

    state = {
        "session_id": "s1",
        "status": "complete",
        "transcript": [
            {
                "skill": "mlops",
                "stop_reason": "resolved",
                "turns": [
                    {
                        "question": "q1",
                        "answer": "a1",
                        "is_follow_up": False,
                        "evaluation": {"dimensions": {}, "weighted_score": 4.0, "confidence": 0.9},
                        "trace": {"llm_calls": 5, "llm_calls_by_provider": [["openai", 4], ["groq", 1]]},
                    }
                ],
            }
        ],
    }

    report = render_session_markdown(state)

    assert "LLM calls: **5**" in report
    assert "openai 4" in report and "groq 1" in report
