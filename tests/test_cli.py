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
from interview_coach.microloop import MicroLoopResult, StopReason, Turn
from interview_coach.rubric import DIMENSIONS
from interview_coach.skill import SkillState
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


def test_session_summary_prints_recorded_error_for_failed_question(capsys):
    # Issue 0018: a genuinely failed question (issue 0014) must show its recorded error in the CLI
    # summary so the reason is visible without opening the Markdown export.
    state = {
        "session_id": "s",
        "status": "complete",
        "question_count": 1,
        "stop_reason": "max_questions",
        "skill_states": {"mlops": {"skill": "mlops", "alpha": 1.0, "beta": 1.0}},
        "skill_metadata": {"mlops": {"role_criticality": "must_have", "evidence_bar": 4}},
        "transcript": [
            {
                "skill": "mlops",
                "plan_index": 0,
                "stop_reason": "failed",
                "resolved_weighted_score": 0.0,
                "resolved_confidence": 0.0,
                "skill_state": {"skill": "mlops", "alpha": 1.0, "beta": 1.0},
                "turns": [],
                "error": "ValueError: interviewer received an unexpected tool call: 'lookup_conparameter'",
            }
        ],
    }

    cli._print_session_summary(state)

    output = capsys.readouterr().out
    assert "stop=failed_recorded_and_skipped" in output
    assert "error: ValueError: interviewer received an unexpected tool call" in output


def test_unknown_resume_message_hints_when_no_checkpoints(tmp_path):
    # Issue 0019: an unknown --resume id fails with a friendly one-liner, not langgraph's raw
    # EmptyInputError traceback.
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(str(tmp_path / "session.sqlite")) as checkpointer:
        message = cli._unknown_session_message("ghost-id", checkpointer, "session.sqlite")

    assert "ghost-id" in message
    assert "No saved Sessions found" in message


def _demo_diagnostic():
    return diagnose(
        CandidateProfile(
            target_role="machine learning engineer",
            claimed_skills={"ml_fundamentals": 4, "mlops": 2},
            target_companies=("Viettel",),
        )
    )


def _suspend_after_first_question(demo, db_path, session_id, *, max_elapsed_seconds=1800.0, started_at=0.0):
    """Pre-seed a checkpoint with one resolved question, suspended before the Supervisor decides."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = build_session_graph(demo, checkpointer=checkpointer)
        state = initial_session_state(
            session_id,
            _demo_diagnostic(),
            max_questions=3,
            max_elapsed_seconds=max_elapsed_seconds,
            started_at=started_at,
        )
        partial = graph.invoke(state, session_config(session_id), interrupt_after=["run_question"])
    assert len(partial["transcript"]) == 1


def test_run_session_graph_does_not_replay_resumed_history_as_live(tmp_path, capsys):
    # Issue 0019: resuming a live Session re-printed every historical question as a "LIVE UPDATE"
    # because seen-questions started at 0. Passing already_seen=<resolved count> must suppress the
    # replay. Reverting `seen_questions = already_seen` to 0 makes this fail.
    from langgraph.checkpoint.sqlite import SqliteSaver

    from interview_coach.demo_llm import DemoLLMClient

    demo = DemoLLMClient()
    db_path = tmp_path / "replay.sqlite"
    session_id = "replay-guard"
    _suspend_after_first_question(demo, db_path, session_id)

    capsys.readouterr()  # drop pre-seed output
    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = build_session_graph(demo, checkpointer=checkpointer)
        cli._run_session_graph(graph, None, session_config(session_id), live=True, already_seen=1)

    output = capsys.readouterr().out
    assert "QUESTION 1 RESOLVED" not in output  # the already-resolved Q1 is not replayed as live


def test_session_refuses_to_restart_over_inflight_checkpoint(tmp_path, monkeypatch, capsys):
    # Issue 0019: forgetting --resume while an in-flight (non-complete) Session exists must not
    # silently restart over it. Deleting the guard makes this return 0 and overwrite progress.
    from interview_coach.demo_llm import DemoLLMClient

    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: DemoLLMClient())
    monkeypatch.setattr(cli, "resumable_session_state", lambda graph, session_id: {"status": "active"})

    rc = cli.main(
        ["session", "--scripted", "--session-id", "busy", "--checkpoint-db", str(tmp_path / "c.sqlite")]
    )

    assert rc == 2
    assert "already in progress" in capsys.readouterr().err


def test_session_starts_fresh_when_prior_checkpoint_is_complete(tmp_path, monkeypatch, capsys):
    # The in-flight guard is scoped to non-complete Sessions: a completed checkpoint may be started over.
    from interview_coach.demo_llm import DemoLLMClient

    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: DemoLLMClient())
    monkeypatch.setattr(cli, "resumable_session_state", lambda graph, session_id: {"status": "complete"})

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--max-questions",
            "1",
            "--session-id",
            "done",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    assert rc == 0
    assert "already in progress" not in capsys.readouterr().err


def test_cmd_session_resume_resets_clock_via_cli(tmp_path, monkeypatch, capsys):
    # Issue 0019: the CLI resume path must reset the elapsed-time budget. Pre-seed a Session "created
    # at epoch" with a 1s budget; resuming later force-completes on the stale wall-clock rail UNLESS
    # the CLI resets started_at. Reverting cli.py's `graph.update_state({"started_at": ...})` makes
    # this fail (stop_reason becomes max_elapsed_seconds).
    from interview_coach.demo_llm import DemoLLMClient

    demo = DemoLLMClient()
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: demo)

    db_path = tmp_path / "clock.sqlite"
    session_id = "gap-cli"
    _suspend_after_first_question(demo, db_path, session_id, max_elapsed_seconds=1.0, started_at=0.0)

    capsys.readouterr()
    rc = cli.main(
        ["session", "--resume", "--scripted", "--no-live", "--session-id", session_id, "--checkpoint-db", str(db_path)]
    )

    output = capsys.readouterr().out
    assert rc == 0
    assert "RESUMING SESSION gap-cli" in output  # the recap is printed instead of replaying history
    assert "stop_reason: max_elapsed_seconds" not in output  # the clock was reset; no stale force-complete


def test_cli_prints_follow_up_unavailable_as_degrade(capsys):
    ev = Evaluation(
        dimensions={"correctness": DimensionScore(score=2, evidence="no evidence")},
        weighted_score=2.0,
        confidence=0.8,
        follow_up_recommended=True,
        follow_up_rationale="needs a probe",
    )
    result = MicroLoopResult(
        skill="ml_fundamentals",
        turns=(
            Turn(
                question="Explain L2 regularization.",
                answer="It makes weights smaller.",
                evaluation=ev,
                is_follow_up=False,
            ),
        ),
        stop_reason=StopReason.FOLLOW_UP_UNAVAILABLE,
        skill_state=SkillState.neutral("ml_fundamentals"),
    )

    cli._print_micro_loop(result)

    output = capsys.readouterr().out
    assert "degraded because a Follow-up was unavailable" in output
    assert "halted by SAFETY CAP" not in output
