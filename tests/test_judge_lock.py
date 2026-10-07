"""The judge fingerprint is ADR 0009's gate, enforced by the suite rather than by review (#141)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interview_coach import evaluator, judge_lock, rubric, telemetry
from interview_coach.bench import render_bench_report
from interview_coach.judge_lock import (
    CANONICAL_CASES,
    JUDGE_LOCK_PATH,
    judge_fingerprint,
    judge_requests,
    load_judge_lock,
    validated_judges,
)
from interview_coach.llm import LLM_CALL_KEY, OpenAIClient

REPO = JUDGE_LOCK_PATH.parent

_PROCEDURE = (
    "The judge changed: the requests it sends are no longer the ones judge.lock pins (ADR 0009). "
    "If that was intended, run the confirm bench (`uv run coach bench --k 3`, repeated per addendum "
    "(f); never widen a band), commit the report under docs/audits/, then set judge.lock's "
    "fingerprint to the one that report is stamped with and point `baseline.artifact` at it. If it "
    "was not intended, the change touched a prompt, a rubric anchor, the schema, the escalation "
    "policy, the model or the temperature — find it and revert it."
)


def test_the_code_fingerprint_is_the_one_judge_lock_pins():
    assert judge_fingerprint() == load_judge_lock()["fingerprint"], _PROCEDURE


def test_the_baseline_artifact_exists_and_is_stamped_or_says_why_not():
    baseline = load_judge_lock()["baseline"]
    artifact = REPO / baseline["artifact"]
    assert artifact.is_file(), f"judge.lock names a bench artifact that does not exist: {artifact}"
    if baseline["stamped"]:
        assert load_judge_lock()["fingerprint"] in artifact.read_text(encoding="utf-8"), (
            "judge.lock says its artifact is stamped, but the artifact does not carry the locked fingerprint"
        )
    else:
        # A pre-#141 artifact cannot carry a stamp; the lock must then say how it was tied to the code.
        assert baseline["provenance"].strip(), "an unstamped baseline needs a provenance note"


def test_the_canonical_cases_cover_every_dimension_mode_and_request_path():
    assert {d for case in CANONICAL_CASES for d in case.rubric.active} == set(rubric.DIMENSIONS)
    assert {case.language_mode for case in CANONICAL_CASES} == {"en", "vn", "mixed"}
    requests = judge_requests(validated_judges()[0])
    assert {case: len(sent) for case, sent in requests.items()} == {
        "en_first_pass": 1,
        "vn_panel": 4,
        "mixed_repairs": 3,
    }
    panel = [r["messages"][0]["content"] for r in requests["vn_panel"]]
    assert panel[1] == evaluator._SKEPTIC_SYSTEM_PROMPT
    assert panel[2] == evaluator._ADVOCATE_SYSTEM_PROMPT
    assert "PANEL VERDICT REQUIRED" in requests["vn_panel"][3]["messages"][1]["content"]
    repairs = [r["messages"][-1]["content"] for r in requests["mixed_repairs"][1:]]
    assert "not a verbatim quote" in repairs[0]
    assert "delivery_fixes" in repairs[1]


def test_it_is_deterministic_and_needs_neither_a_provider_nor_the_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    before = telemetry.snapshot().get(LLM_CALL_KEY, 0)
    assert judge_fingerprint() == judge_fingerprint()
    assert not ledger.exists(), "computing the fingerprint must not touch the usage ledger"
    assert telemetry.snapshot().get(LLM_CALL_KEY, 0) == before, "computing the fingerprint made a provider call"


def _judge(**overrides: object) -> OpenAIClient:
    seated = validated_judges()[0]
    return OpenAIClient(seated._settings.model_copy(update=overrides))


@pytest.mark.parametrize(
    "change",
    [
        "system_prompt",
        "evidence_repair",
        "rubric_anchor",
        "skeptic_prompt",
        "temperature",
        "model",
        "endpoint",
    ],
)
def test_every_judge_surface_change_moves_it(change, monkeypatch):
    locked = judge_fingerprint()
    judges = None
    if change == "system_prompt":
        monkeypatch.setattr(evaluator, "_SYSTEM_PROMPT_CORE", evaluator._SYSTEM_PROMPT_CORE + " Be strict.")
    elif change == "evidence_repair":
        monkeypatch.setattr(evaluator, "_EVIDENCE_RULE", evaluator._EVIDENCE_RULE + " Quote exactly.")
    elif change == "rubric_anchor":
        monkeypatch.setitem(rubric.DIMENSION_GUIDE, "depth", rubric.DIMENSION_GUIDE["depth"] + " 3 = one causal step.")
    elif change == "skeptic_prompt":
        monkeypatch.setattr(evaluator, "_SKEPTIC_SYSTEM_PROMPT", evaluator._SKEPTIC_SYSTEM_PROMPT + " Be harsh.")
    elif change == "temperature":
        judges = [_judge(temperature=0.3)]
    elif change == "model":
        judges = [_judge(model="gpt-5.4")]
    elif change == "endpoint":
        judges = [_judge(base_url="https://proxy.example.com/v1")]
    assert judge_fingerprint(judges) != locked


def test_an_escalation_policy_change_fails_loudly_instead_of_fingerprinting_a_shorter_walk(monkeypatch):
    # At 0.25 the vn_panel case's 0.3 first pass no longer escalates, so three scripted Panel replies
    # go unused. Hashing the shorter walk would hide the policy change; refusing surfaces it.
    monkeypatch.setattr(evaluator, "SELF_CRITIQUE_CONFIDENCE_THRESHOLD", 0.25)
    with pytest.raises(RuntimeError, match="no longer walks its path"):
        judge_fingerprint()


def test_a_change_to_how_replies_are_post_processed_does_not_move_it(monkeypatch):
    # The noise haircut runs on the judge's reply, after every request has been sent. It changes the
    # kept confidence, never what the judge is asked, so it is not a judge-surface change.
    locked = judge_fingerprint()
    monkeypatch.setattr(evaluator, "NOISE_CONFIDENCE_CEILING", 0.5)
    assert judge_fingerprint() == locked


def test_the_bench_report_is_stamped_with_the_fingerprint_it_measured():
    report = render_bench_report([], provider="openai", model="gpt-5.4-mini", judge_fingerprint="sha256:abc")
    assert "- Judge fingerprint: `sha256:abc`" in report
    assert "Judge fingerprint" not in render_bench_report([], provider="openai", model="gpt-5.4-mini")


def test_the_lock_file_is_plain_json_with_the_fields_the_gate_reads():
    data = json.loads(Path(JUDGE_LOCK_PATH).read_text(encoding="utf-8"))
    assert data["fingerprint"].startswith("sha256:")
    assert {"artifact", "result", "red_cases", "stamped", "provenance"} <= set(data["baseline"])
    assert judge_lock.JUDGE_LOCK_PATH == REPO / "judge.lock"


def test_coach_bench_prints_and_stamps_the_fingerprint_of_the_judge_it_ran(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from interview_coach import cli

    # The validated judge with a key, so it is a real provider client; run_bench is stubbed, so no call leaves.
    judge = _judge(api_key="sk-test")
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(configured=True, primary_provider="openai", primary_config=judge._settings),
    )
    monkeypatch.setattr(cli, "build_client", lambda settings: judge)
    monkeypatch.setattr(cli, "run_bench", lambda judge, cases, *, k=1: [])
    out = tmp_path / "report.md"

    cli.main(["bench", "--k", "1", "--ignore-budget", "--out", str(out)])

    locked = load_judge_lock()["fingerprint"]
    assert f"Judge fingerprint {locked} (matches judge.lock)." in capsys.readouterr().out
    assert f"- Judge fingerprint: `{locked}` (#141)" in out.read_text(encoding="utf-8")


def test_coach_bench_says_when_its_judge_is_not_the_locked_one(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from interview_coach import cli

    judge = _judge(api_key="sk-test", temperature=0.7)  # an env override the lock does not pin
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(configured=True, primary_provider="openai", primary_config=judge._settings),
    )
    monkeypatch.setattr(cli, "build_client", lambda settings: judge)
    monkeypatch.setattr(cli, "run_bench", lambda judge, cases, *, k=1: [])

    cli.main(["bench", "--k", "1", "--ignore-budget", "--out", str(tmp_path / "report.md")])

    assert "DIFFERS from judge.lock: this run measures a judge change" in capsys.readouterr().out
