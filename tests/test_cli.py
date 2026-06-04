"""CLI dispatch wiring for ``diagnose`` (issue 0009 follow-up).

The LLM Diagnostic agent must be the *default* Topic Plan path whenever a provider is configured,
with the deterministic path as the offline fallback — not an opt-in flag. These tests pin that
wiring at the ``main()`` boundary without touching a real provider.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from interview_coach import cli
from interview_coach.diagnostic import CandidateProfile, DiagnosticResult, TopicPlanSource, diagnose
from interview_coach.eval_harness import GoldenAnswerCase, GoldenAnswerResult
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.fixtures import QUESTION
from interview_coach.rubric import DIMENSIONS
from interview_coach.supervisor import build_session_graph, initial_session_state, session_config


@pytest.fixture
def spy_diagnose(monkeypatch):
    """Replace ``cli.diagnose`` with a spy that records the client it was handed."""
    captured: dict[str, object] = {}

    def _fake_diagnose(profile, client=None):
        captured["client"] = client
        source = TopicPlanSource.LLM if client is not None else TopicPlanSource.DETERMINISTIC
        return DiagnosticResult(topic_plan=(), priors={}, topic_plan_source=source)

    monkeypatch.setattr(cli, "diagnose", _fake_diagnose)
    return captured


def _settings(*, configured: bool) -> SimpleNamespace:
    return SimpleNamespace(configured=configured, primary_provider="mimo")


def test_diagnose_uses_llm_agent_by_default_when_configured(monkeypatch, spy_diagnose):
    sentinel = object()
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: sentinel)

    rc = cli.main(["diagnose", "--target-role", "machine learning engineer"])

    assert rc == 0
    assert spy_diagnose["client"] is sentinel  # agent path, no --agent flag needed


def test_diagnose_falls_back_to_deterministic_when_unconfigured(monkeypatch, spy_diagnose):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=False))

    def _no_build(settings):
        raise AssertionError("must not build a client when the provider is unconfigured")

    monkeypatch.setattr(cli, "build_client", _no_build)

    rc = cli.main(["diagnose", "--target-role", "machine learning engineer"])

    assert rc == 0  # offline fallback, not the exit-2 error the strict commands raise
    assert spy_diagnose["client"] is None


def test_diagnose_offline_flag_forces_deterministic_even_when_configured(monkeypatch, spy_diagnose):
    def _no_settings():
        raise AssertionError("--offline must not even load settings")

    monkeypatch.setattr(cli, "load_settings", _no_settings)

    rc = cli.main(["diagnose", "--offline", "--target-role", "machine learning engineer"])

    assert rc == 0
    assert spy_diagnose["client"] is None


def test_required_llm_command_still_errors_when_unconfigured(monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=False))

    assert cli.main(["evaluate"]) == 2


def _harness_result(score: float, *, expected_min: float = 1.0, expected_max: float = 5.0) -> GoldenAnswerResult:
    return GoldenAnswerResult(
        case=GoldenAnswerCase(
            case_id="fixture_case",
            answer="fixture",
            expected_min=expected_min,
            expected_max=expected_max,
        ),
        evaluation=Evaluation(
            dimensions={
                dim: DimensionScore(score=round(score), evidence="no evidence")
                for dim in QUESTION.rubric.active
            },
            weighted_score=score,
            confidence=0.8,
            follow_up_recommended=False,
            follow_up_rationale="resolved",
        ),
    )


def test_eval_harness_command_uses_configured_client(monkeypatch, capsys):
    sentinel = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: sentinel)

    def _fake_harness(client):
        captured["client"] = client
        return [_harness_result(3.0)]

    monkeypatch.setattr(cli, "run_golden_answer_harness", _fake_harness)

    rc = cli.main(["eval-harness"])

    assert rc == 0
    assert captured["client"] is sentinel
    assert "summary: 1/1 passed" in capsys.readouterr().out


def test_eval_harness_command_returns_nonzero_on_regression(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: object())
    monkeypatch.setattr(
        cli,
        "run_golden_answer_harness",
        lambda client: [_harness_result(5.0, expected_min=1.0, expected_max=2.5)],
    )

    rc = cli.main(["eval-harness"])

    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_default_suppresses_noisy_info_logs(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: object())

    def _fake_harness(client):
        logging.getLogger("httpx").info("HTTP Request: noisy provider log")
        return [_harness_result(3.0)]

    monkeypatch.setattr(cli, "run_golden_answer_harness", _fake_harness)

    assert cli.main(["eval-harness"]) == 0
    captured = capsys.readouterr()
    assert "HTTP Request" not in captured.err


def test_cli_verbose_shows_info_logs(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: object())

    def _fake_harness(client):
        logging.getLogger("httpx").info("HTTP Request: visible provider log")
        return [_harness_result(3.0)]

    monkeypatch.setattr(cli, "run_golden_answer_harness", _fake_harness)

    assert cli.main(["--verbose", "eval-harness"]) == 0
    captured = capsys.readouterr()
    assert "HTTP Request: visible provider log" in captured.err


def test_run_session_graph_prints_live_skill_state_updates(make_client, capsys):
    client, _ = make_client(
        [
            json.dumps(
                {
                    "dimensions": {
                        dim: {"score": 5, "evidence": "no evidence"}
                        for dim in DIMENSIONS
                    },
                    "weighted_score": 5.0,
                    "confidence": 0.8,
                    "follow_up_recommended": False,
                    "follow_up_rationale": "resolved",
                }
            ),
            '{"bad": 1}',
            '{"bad": 1}',
        ]
    )
    diagnostic = diagnose(
        CandidateProfile(
            target_role="machine learning engineer",
            claimed_skills={"ml_fundamentals": 4, "mlops": 2},
            target_companies=("Viettel",),
        )
    )
    state = initial_session_state("live-cli-session", diagnostic, max_questions=1, started_at=0)
    graph = build_session_graph(client, now=lambda: 1)

    final = cli._run_session_graph(graph, state, session_config("live-cli-session"), live=True)

    assert final["question_count"] == 1
    output = capsys.readouterr().out
    assert "LIVE UPDATE: QUESTION 1 RESOLVED" in output
    assert "--- SKILL STATES ---" in output
    assert "mlops" in output
