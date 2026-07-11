"""Rejection post-mortem agent (issue 0026, ADRs 0002/0005/0006).

Pins the four acceptance criteria offline: (1) the adaptive elicitation dialogue converts a messy
recollection into a typed reconstructed evaluation per probed Skill with explicit second-hand
confidence; (2) the ledger fuses it at the reduced, documented ``POSTMORTEM_WEIGHT_RATIO`` — with
decay applied BEFORE observing — and the Study Plan diff regenerates on the after-state; (3) a
mid-elicitation abort is Candidate intent per ADR 0005: exit 2, partial recollection discarded,
ledger byte-identical; (4) the recollection → typed-evidence conversion runs end-to-end on the
scripted fixture pipeline (FakeOpenAI + ScriptedCandidate).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from interview_coach import cli
from interview_coach.evaluator import Evaluation
from interview_coach.ledger import SECONDS_PER_DAY, decay_beta, load_states, save_posteriors
from interview_coach.llm import StructuredOutputError
from interview_coach.microloop import ScriptedCandidate
from interview_coach.postmortem import (
    MAX_ELICITATION_QUESTIONS,
    MIN_ELICITATION_QUESTIONS,
    RecollectionTurn,
    ReconstructedScorecard,
    ReconstructedSkillEntry,
    fuse_scorecard,
    reconstruct_scorecard,
    run_elicitation,
    run_postmortem,
)
from interview_coach.skill import (
    POSTMORTEM_WEIGHT_RATIO,
    SkillState,
    apply_evaluation,
    confidence_weight,
    score_to_quality,
)

NOW = 1_000_000.0


def _evaluation(weighted_score: float, confidence: float) -> Evaluation:
    """A minimal live Evaluation for the postmortem-vs-live weight comparison."""
    return Evaluation(
        dimensions={},
        weighted_score=weighted_score,
        confidence=confidence,
        follow_up_recommended=False,
        follow_up_rationale="n/a",
    )


def _step(done: bool, question: str = "What did they ask first?") -> str:
    return json.dumps({"done": done, "next_question": question, "coverage": ["mlops"]})


def _entry(skill: str = "mlops", score: float = 2.0, confidence: float = 0.4) -> dict:
    return {
        "skill": skill,
        "estimated_score": score,
        "confidence": confidence,
        "rationale": "the interviewer pushed back twice on rollout strategy",
        "recollection_evidence": "they kept asking how I would roll back a bad deploy",
    }


def _scorecard(*entries: dict) -> str:
    return json.dumps({"entries": list(entries) or [_entry()]})


def _elicitation_replies(n: int = MIN_ELICITATION_QUESTIONS) -> list[str]:
    """n not-done steps followed by a done step: n questions asked over n+1 chat_json calls."""
    return [_step(False, f"Debrief question {i}?") for i in range(1, n + 1)] + [_step(True)]


def _answers(n: int = MIN_ELICITATION_QUESTIONS) -> list[str]:
    return [f"recollection {i}" for i in range(1, n + 1)]


def _transcript() -> tuple[RecollectionTurn, ...]:
    return tuple(
        RecollectionTurn(question=f"Q{i}", answer=f"A{i}")
        for i in range(1, MIN_ELICITATION_QUESTIONS + 1)
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(configured=True, primary_provider="mimo")


# --- end-to-end: recollection -> typed evidence -> ledger fusion (THE acceptance criterion) ------


def test_recollection_to_typed_evidence_updates_ledger_end_to_end(tmp_path, make_client):
    path = tmp_path / "ledger.json"
    save_posteriors(
        path,
        "alice",
        {
            "mlops": SkillState("mlops", alpha=8.0, beta=2.0),
            "deep_learning": SkillState("deep_learning", alpha=3.0, beta=3.0),
        },
        now=NOW,
    )
    score, conf = 2.0, 0.4
    client, fake = make_client(
        [
            *_elicitation_replies(),
            _scorecard(_entry(score=score, confidence=conf)),
            "{}",  # planner draft attempt — schema-invalid on purpose: the LLM diff layer degrades
            "{}",  # planner retry — also invalid; the fusion must survive without a plan
        ]
    )

    result = run_postmortem(
        client, ScriptedCandidate(_answers()), candidate_id="alice", ledger_db=path, now=NOW
    )

    # Exact fusion property (mirrors test_skill.py's exactness): alpha/beta move by precisely
    # POSTMORTEM_WEIGHT_RATIO * confidence_weight(conf) pseudo-counts split by quality.
    weight = POSTMORTEM_WEIGHT_RATIO * confidence_weight(conf)
    quality = score_to_quality(score)
    after = result.states_after["mlops"]
    assert after.alpha == pytest.approx(8.0 + weight * quality)
    assert after.beta == pytest.approx(2.0 + weight * (1.0 - quality))
    # The untouched Skill's mass rides along the whole-record re-save unchanged.
    assert result.states_after["deep_learning"].alpha == pytest.approx(3.0)
    assert result.states_after["deep_learning"].beta == pytest.approx(3.0)
    # Persisted: reloading the ledger returns exactly what fusion produced.
    reloaded = load_states(path, "alice", now=NOW)
    assert reloaded["mlops"].alpha == pytest.approx(after.alpha)
    assert reloaded["mlops"].beta == pytest.approx(after.beta)
    assert reloaded["deep_learning"].beta == pytest.approx(3.0)
    # Typed reconstructed evaluation with explicit second-hand confidence.
    entry = result.scorecard.entries[0]
    assert entry.skill == "mlops"
    assert entry.confidence == pytest.approx(conf)
    assert entry.recollection_evidence
    # Deterministic diff layer: a bad real-world data point raises the Skill's study priority.
    before_target = {t.skill: t for t in result.targets_before}["mlops"]
    after_target = {t.skill: t for t in result.targets_after}["mlops"]
    assert after_target.priority_score > before_target.priority_score
    # LLM plan layer degraded gracefully; the fusion above still stands.
    assert result.study_plan is None
    assert result.study_plan_error
    assert fake.call_count == 9  # 6 elicitation + 1 reconstruction + 2 planner attempts


def test_run_postmortem_requires_a_candidate_id(tmp_path, make_client):
    # The ledger is the whole point (issue 0026); an empty id would silently no-op both ledger I/O.
    client, fake = make_client([_step(False)])
    with pytest.raises(ValueError):
        run_postmortem(
            client, ScriptedCandidate(["a"]), candidate_id="", ledger_db=tmp_path / "ledger.json"
        )
    assert fake.call_count == 0  # fails at setup, before any LLM call


# --- weight properties (property-style, mirror test_skill.py) ------------------------------------


def test_postmortem_shift_is_strictly_smaller_than_live_at_same_score_and_confidence():
    before = SkillState.neutral("mlops")
    scorecard = ReconstructedScorecard(
        entries=[ReconstructedSkillEntry(**_entry(score=5.0, confidence=0.8))]
    )
    fused = fuse_scorecard({"mlops": before}, scorecard)["mlops"]
    live = apply_evaluation(before, _evaluation(5.0, 0.8))

    # Same score, same confidence: the second-hand shift is strictly smaller than the live one.
    assert live.mastery > fused.mastery > before.mastery
    # And exactly the documented ratio's worth of evidence mass — no silent recalibration.
    assert fused.alpha - before.alpha == pytest.approx(POSTMORTEM_WEIGHT_RATIO * (live.alpha - before.alpha))
    assert fused.beta - before.beta == pytest.approx(POSTMORTEM_WEIGHT_RATIO * (live.beta - before.beta))


def test_postmortem_weight_ratio_is_the_documented_half():
    # Issue 0026: "roughly half normal weight; document the ratio" — changing it is a conscious
    # recalibration, not a drive-by edit.
    assert POSTMORTEM_WEIGHT_RATIO == pytest.approx(0.5)


def test_unmentioned_skills_pass_through_fusion_untouched():
    states = {
        "mlops": SkillState("mlops", alpha=8.0, beta=2.0),
        "system_design": SkillState("system_design", alpha=4.0, beta=4.0),
    }
    scorecard = ReconstructedScorecard(entries=[ReconstructedSkillEntry(**_entry())])
    fused = fuse_scorecard(states, scorecard)
    assert fused["system_design"] == states["system_design"]


# --- decay-before-observe (ADR 0006) --------------------------------------------------------------


def test_stale_ledger_record_decays_before_observing(tmp_path):
    # save_posteriors restamps completed_at, so observing un-decayed params would silently
    # un-decay stale evidence — decay must happen first, in load_states.
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=9.0, beta=1.0)}, now=0.0)
    states = load_states(path, "alice", now=30.0 * SECONDS_PER_DAY)

    expected_alpha, expected_beta = decay_beta(9.0, 1.0, 30.0)
    assert states["mlops"].alpha == pytest.approx(expected_alpha)
    assert states["mlops"].beta == pytest.approx(expected_beta)

    score, conf = 2.0, 0.4
    scorecard = ReconstructedScorecard(
        entries=[ReconstructedSkillEntry(**_entry(score=score, confidence=conf))]
    )
    fused = fuse_scorecard(states, scorecard)["mlops"]
    weight = POSTMORTEM_WEIGHT_RATIO * confidence_weight(conf)
    assert fused.alpha == pytest.approx(expected_alpha + weight * score_to_quality(score))
    assert fused.beta == pytest.approx(expected_beta + weight * (1.0 - score_to_quality(score)))


# --- elicitation loop discipline (Python's, not the model's) --------------------------------------


def test_premature_done_is_ignored_before_the_minimum(make_client):
    # The model declares done from question 2 onward; the loop keeps debriefing until MIN.
    client, fake = make_client([_step(False, "Q1?"), _step(True, "Q2?")])  # last reply repeats
    transcript = run_elicitation(client, ScriptedCandidate(_answers(MIN_ELICITATION_QUESTIONS)))
    assert len(transcript) == MIN_ELICITATION_QUESTIONS
    assert fake.call_count == MIN_ELICITATION_QUESTIONS + 1  # one final step to accept done


def test_never_done_forces_stop_at_the_maximum(make_client):
    client, fake = make_client([_step(False)])
    transcript = run_elicitation(
        client, ScriptedCandidate(_answers(MAX_ELICITATION_QUESTIONS + 3))
    )
    assert len(transcript) == MAX_ELICITATION_QUESTIONS
    assert fake.call_count == MAX_ELICITATION_QUESTIONS  # budget spent: the model is not consulted again


# --- abort is intent (ADR 0005) -------------------------------------------------------------------


def test_abort_mid_elicitation_exits_2_and_leaves_ledger_byte_identical(
    tmp_path, monkeypatch, make_client, capsys
):
    # Mirror of test_candidate_intent_aborts_session_and_is_not_recorded_as_failed: the scripted
    # Candidate runs out mid-debrief (CandidateExhausted, a CandidateIntent) — clean exit 2, the
    # partial recollection is discarded, and the ledger file is BYTE-identical (zero writes).
    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=0.0)
    before_bytes = path.read_bytes()
    client, _ = make_client([_step(False)])
    monkeypatch.setattr(cli, "load_settings", _settings)
    monkeypatch.setattr(cli, "build_client", lambda settings: client)

    rc = cli.main(
        [
            "postmortem",
            "--candidate",
            "alice",
            "--ledger-db",
            str(path),
            "--scripted-recollection",
            "a1",
            "--scripted-recollection",
            "a2",
        ]
    )

    assert rc == 2
    assert path.read_bytes() == before_bytes
    captured = capsys.readouterr()
    assert "discarded" in captured.err
    assert "RECONSTRUCTED SCORECARD" not in captured.out  # no scorecard from a partial debrief


# --- reconstruction validators ---------------------------------------------------------------------


def test_unknown_skill_is_retried_once_with_error_feedback_then_accepted(make_client):
    client, fake = make_client(
        [_scorecard(_entry(skill="basket_weaving")), _scorecard(_entry(skill="mlops"))]
    )
    scorecard = reconstruct_scorecard(client, _transcript())
    assert [entry.skill for entry in scorecard.entries] == ["mlops"]
    assert fake.call_count == 2
    retry_prompt = fake.chat.completions.calls[1]["messages"][-1]["content"]
    assert "basket_weaving" in retry_prompt  # the validator's error steers the retry


def test_unknown_skill_twice_hard_fails(make_client):
    bad = _scorecard(_entry(skill="basket_weaving"))
    client, fake = make_client([bad, bad])
    with pytest.raises(StructuredOutputError):
        reconstruct_scorecard(client, _transcript())
    assert fake.call_count == 2  # exactly one retry, then hard fail


def test_blank_recollection_evidence_is_rejected(make_client):
    bad = _scorecard({**_entry(), "recollection_evidence": "   "})
    client, fake = make_client([bad, bad])
    with pytest.raises(StructuredOutputError):
        reconstruct_scorecard(client, _transcript())
    assert fake.call_count == 2


# --- study-plan regeneration (LLM layer of the diff) ------------------------------------------------


def test_plan_regenerates_on_the_after_state(tmp_path, make_client, monkeypatch):
    from interview_coach import postmortem

    path = tmp_path / "ledger.json"
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=NOW)
    seen: dict[str, object] = {}
    plan_dump = {"readiness_estimate": 0.4, "readiness_rationale": "r", "prioritized_topics": []}

    def _spy_plan(client, session_state, *, resource_store=None, **kwargs):
        seen["skill_states"] = session_state["skill_states"]
        seen["skill_metadata"] = session_state["skill_metadata"]
        return SimpleNamespace(model_dump=lambda mode: plan_dump)

    monkeypatch.setattr(postmortem, "plan_study", _spy_plan)
    score, conf = 2.0, 0.4
    client, fake = make_client(
        [*_elicitation_replies(), _scorecard(_entry(score=score, confidence=conf))]
    )

    result = run_postmortem(
        client, ScriptedCandidate(_answers()), candidate_id="alice", ledger_db=path, now=NOW
    )

    # The planner sees the AFTER (fused) state, with role-criticality metadata synthesized.
    weight = POSTMORTEM_WEIGHT_RATIO * confidence_weight(conf)
    assert seen["skill_states"]["mlops"]["alpha"] == pytest.approx(8.0 + weight * score_to_quality(score))
    assert seen["skill_metadata"]["mlops"]["role_criticality"] == "must_have"  # default MLE role
    assert result.study_plan == plan_dump
    assert result.study_plan_error is None
    assert fake.call_count == 7  # 6 elicitation + 1 reconstruction; the spy planner makes no call


# --- CLI boundary ----------------------------------------------------------------------------------


def test_cli_postmortem_end_to_end_with_markdown_export(tmp_path, monkeypatch, make_client, capsys):
    path = tmp_path / "ledger.json"
    now = time.time()
    save_posteriors(path, "alice", {"mlops": SkillState("mlops", alpha=8.0, beta=2.0)}, now=now)
    client, _ = make_client([*_elicitation_replies(), _scorecard(_entry()), "{}", "{}"])
    monkeypatch.setattr(cli, "load_settings", _settings)
    monkeypatch.setattr(cli, "build_client", lambda settings: client)
    md_path = tmp_path / "postmortem.md"
    argv = [
        "postmortem",
        "--candidate",
        "alice",
        "--ledger-db",
        str(path),
        "--export-markdown",
        str(md_path),
    ]
    for answer in _answers():
        argv += ["--scripted-recollection", answer]

    rc = cli.main(argv)

    assert rc == 0
    out = capsys.readouterr().out
    assert "RECONSTRUCTED SCORECARD" in out
    assert "STUDY PRIORITIES: BEFORE -> AFTER FUSION" in out
    assert "planner unavailable" in out  # degraded LLM layer is reported, not fatal
    report = md_path.read_text(encoding="utf-8")
    assert "## Reconstructed Scorecard" in report
    assert "## Ledger Delta" in report
    assert "## Regenerated Plan" in report
    # The ledger genuinely moved: score 2.0 at conf 0.4 adds ~0.41 to beta at the reduced weight.
    reloaded = load_states(path, "alice", now=time.time())
    assert reloaded["mlops"].beta > 2.3
