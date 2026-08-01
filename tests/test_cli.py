"""CLI dispatch wiring for ``diagnose`` (issue 0009 follow-up).

The LLM Diagnostic agent must be the *default* Topic Plan path whenever a provider is configured,
with the deterministic path as the offline fallback — not an opt-in flag. These tests pin that
wiring at the ``main()`` boundary without touching a real provider.
"""

from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace

import pytest

from interview_coach import cli, usage
from interview_coach.demo_llm import DemoLLMClient
from interview_coach.diagnostic import CandidateProfile, DiagnosticResult, TopicPlanSource, diagnose
from interview_coach.eval_harness import GoldenAnswerCase, GoldenAnswerResult
from interview_coach.evaluator import DimensionScore, Evaluation
from interview_coach.fixtures import QUESTION
from interview_coach.microloop import DEFAULT_MAX_TURNS, MicroLoopResult, StopReason, Turn
from interview_coach.rubric import DIMENSIONS
from interview_coach.skill import SkillState
from interview_coach.supervisor import build_session_graph, initial_session_state, session_config


@pytest.fixture
def spy_diagnose(monkeypatch):
    """Replace ``cli.diagnose_or_degrade`` with a spy that records the client it was handed."""
    captured: dict[str, object] = {}

    def _fake_diagnose(profile, client=None):
        captured["client"] = client
        source = TopicPlanSource.LLM if client is not None else TopicPlanSource.DETERMINISTIC
        return DiagnosticResult(topic_plan=(), priors={}, topic_plan_source=source)

    monkeypatch.setattr(cli, "diagnose_or_degrade", _fake_diagnose)
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
                dim: DimensionScore(score=round(score), evidence="no evidence") for dim in QUESTION.rubric.active
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
                    "dimensions": {dim: {"score": 5, "evidence": "no evidence"} for dim in DIMENSIONS},
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

    rc = cli.main(["session", "--scripted", "--session-id", "busy", "--checkpoint-db", str(tmp_path / "c.sqlite")])

    assert rc == 2
    assert "already in progress" in capsys.readouterr().err


def test_session_language_flag_reaches_the_summary(tmp_path, monkeypatch, capsys):
    # Issue 0024: --language threads CLI -> initial_session_state -> final state -> summary/export.
    from interview_coach.demo_llm import DemoLLMClient

    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: DemoLLMClient())

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--language",
            "mixed",
            "--max-questions",
            "1",
            "--session-id",
            "lang-flag",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "language_mode: mixed" in out
    # --no-live is a branch of the streaming loop now (R-25 needs the node boundary the rail hangs
    # off), so its suppression of live updates has to stay pinned.
    assert "LIVE UPDATE" not in out


def test_session_rejects_unknown_language_flag(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["session", "--scripted", "--language", "vi", "--session-id", "bad-lang"])
    assert excinfo.value.code == 2
    assert "--language" in capsys.readouterr().err


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


# --- R-12: `coach api` refuses to fork workers ---------------------------------------------------


@pytest.fixture
def uvicorn_spy(monkeypatch):
    """Record `uvicorn.run` calls instead of binding a port."""
    import uvicorn

    calls: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    return calls


def test_coach_api_refuses_to_start_under_web_concurrency(monkeypatch, uvicorn_spy, capsys):
    # Docker's CMD is `coach api`, and compose feeds `.env` straight in — so a stray WEB_CONCURRENCY
    # would fork workers through the documented path with nothing printed about it.
    monkeypatch.setenv("WEB_CONCURRENCY", "3")

    rc = cli.main(["api"])

    assert rc == 2
    assert uvicorn_spy == []
    assert "WEB_CONCURRENCY" in capsys.readouterr().err


def test_coach_api_starts_normally_with_no_worker_config(uvicorn_spy):
    # WEB_CONCURRENCY and COACH_LOG_FILE are cleared for every test by conftest, precisely because
    # `monkeypatch.delenv` cannot undo a variable the code under test creates.
    assert cli.main(["api"]) == 0
    assert len(uvicorn_spy) == 1


def test_log_file_flag_reaches_the_serving_process(uvicorn_spy, tmp_path):
    # `--reload` serves from a spawned subprocess that never runs `_cmd_api`; the environment is the
    # only channel that crosses that boundary, so the flag has to be exported before uvicorn starts.
    # That this env var is *read* — and that a record lands in the file — is pinned end-to-end by
    # `test_the_log_file_env_var_is_actually_read_by_the_serving_process` in tests/test_web_api.py.
    log_file = tmp_path / "api.log"

    assert cli.main(["api", "--log-file", str(log_file)]) == 0
    assert os.environ["COACH_LOG_FILE"] == str(log_file)
    assert len(uvicorn_spy) == 1


def test_the_exported_log_file_does_not_outlive_the_test_that_exported_it():
    # Deliberately order-coupled to the test directly above — a leak is by definition something the
    # *next* test sees, and no test can assert its own teardown. `_cmd_api` writes into the real
    # os.environ (it has to; that is the only channel a `--reload` subprocess reads), pointing at a
    # tmp_path pytest deletes on the way out. conftest's autouse teardown is what sweeps it, and
    # deleting that fixture left the whole suite green until this assertion existed.
    assert "COACH_LOG_FILE" not in os.environ
# --- R-25: the free-tier budget rail on the CLI surface ------------------------------------------


class _ProviderDemoClient(DemoLLMClient):
    """A demo brain that carries a provider identity.

    DemoLLMClient is exempt from every budget rail BY DESIGN (``provider_label`` -> "unknown": it
    spends nobody's allowance), which is exactly what keeps the rest of the suite untouched — and
    also what makes it useless for testing the rail. This double is the smallest thing that is
    subject to the rail while still running a Session deterministically and offline.
    """

    provider_name = "mimo"


def _tmp_ledger(monkeypatch, tmp_path):
    """Point the ledger at tmp_path — a rail test must never write to the repo's real ledger.

    Also clears the rail's env vars: they are read straight from ``os.environ``, so a developer with
    a low budget exported in their shell would otherwise get different results from CI.
    """
    ledger = tmp_path / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    for name in ("LLM_DAILY_TOKEN_BUDGET", "LLM_SESSION_TOKEN_BUDGET", "COACH_DAILY_QUESTION_CAP"):
        monkeypatch.delenv(name, raising=False)
    return ledger


def test_a_suspend_still_shows_the_question_that_was_just_resolved(tmp_path, capsys):
    # A live Session that suspends must acknowledge the answer the Candidate just gave — it IS in
    # the checkpoint. Checking the rail before printing makes a suspend look like it ate the answer.
    from langgraph.checkpoint.sqlite import SqliteSaver

    demo = DemoLLMClient()
    db_path = tmp_path / "ordering.sqlite"
    session_id = "ordering"

    def stop_after_the_first_question(state):
        return "out of budget" if state.get("question_count", 0) >= 1 else None

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = build_session_graph(demo, checkpointer=checkpointer)
        state = initial_session_state(session_id, _demo_diagnostic(), max_questions=3, started_at=0.0)
        with pytest.raises(cli.SessionBudgetSuspended):
            cli._run_session_graph(
                graph, state, session_config(session_id), live=True, budget_stop=stop_after_the_first_question
            )

    captured = capsys.readouterr()
    assert "LIVE UPDATE: QUESTION 1 RESOLVED" in captured.out
    assert "SESSION SUSPENDED" in captured.err


def test_session_refuses_to_start_into_a_spent_daily_budget(tmp_path, monkeypatch, capsys):
    # AC (b): the Session refuses to START rather than dying partway in. Deleting the gate in
    # _cmd_session makes this return 0 and spend a real Diagnostic call.
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "1000")
    usage.record_usage("mimo", "test-model", prompt_tokens=900, completion_tokens=50)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _ProviderDemoClient())

    def _never(*args, **kwargs):
        raise AssertionError("the start gate must refuse BEFORE any token is spent")

    monkeypatch.setattr(cli, "diagnose_or_degrade", _never)

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--max-questions",
            "2",
            "--session-id",
            "broke",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    err = capsys.readouterr().err
    assert rc == 2
    assert "00:00 UTC" in err  # the remedy is named, not just the refusal
    assert f"~{usage.estimated_session_tokens(2):,}" in err  # ...and the estimate it was refused against


def test_session_starts_when_the_day_can_fund_it(tmp_path, monkeypatch, capsys):
    # The other direction of the same gate: a rail that fires on compliant behaviour is a bug.
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(usage.estimated_session_tokens(1)))
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _ProviderDemoClient())

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--max-questions",
            "1",
            "--session-id",
            "funded",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    assert rc == 0
    assert "00:00 UTC" not in capsys.readouterr().err


def test_demo_mode_is_exempt_from_every_budget_rail(tmp_path, monkeypatch, capsys):
    # THE exemption predicate. DemoLLMClient carries no provider identity, so it spends nobody's
    # allowance and every rail must be inert for it — that is what keeps demo mode free and the rest
    # of this suite unchanged. Forcing `metered = True` makes this refuse with rc 2.
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "0")
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "0")
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "0")
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: DemoLLMClient())

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--max-questions",
            "1",
            "--session-id",
            "demo-exempt",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    assert rc == 0
    assert "(complete)" in capsys.readouterr().out


def test_the_rail_counts_only_the_questions_actually_left(tmp_path, monkeypatch, capsys):
    # The mid-Session estimate must use max_questions MINUS the ones already resolved. Dropping the
    # subtraction keeps charging for questions that are already paid for, and suspends a Session
    # that can comfortably afford the rest of itself.
    class _Metered(_ProviderDemoClient):
        def chat_json(self, *args, **kwargs):
            usage.record_usage("mimo", "test-model", prompt_tokens=500, completion_tokens=0)
            return super().chat_json(*args, **kwargs)

    _tmp_ledger(monkeypatch, tmp_path)
    # Exactly what the start gate demands for 2 questions — and, once Q1 is resolved and paid for,
    # comfortably more than the one question that is genuinely left.
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(usage.estimated_session_tokens(2)))
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _Metered())

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--max-questions",
            "2",
            "--session-id",
            "counts-left",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    assert rc == 0
    assert "(complete)" in capsys.readouterr().out


def test_budget_breach_suspends_and_never_records_a_failed_question(tmp_path, monkeypatch, capsys):
    # THE issue's test (ADR 0005's third category). A mid-Session budget breach must SUSPEND:
    #   - never `failed`-and-advance (that is fake evidence about the Candidate),
    #   - never a silent stall,
    #   - and the checkpoint must still be resumable to completion.
    # Without the rail the Session runs straight to `complete`. With the stop mis-sited INSIDE the
    # graph it is caught by question_node's `except Exception` net and becomes stop_reason="failed",
    # which assertion (b) below catches.
    from langgraph.checkpoint.sqlite import SqliteSaver

    from interview_coach.supervisor import resumable_session_state

    demo = _ProviderDemoClient()
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: demo)

    db_path = tmp_path / "suspend.sqlite"
    session_id = "budget-breach"
    _suspend_after_first_question(demo, db_path, session_id)
    capsys.readouterr()

    # The day is spent: resuming cannot fund the remaining questions.
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "10")
    usage.record_usage("mimo", "test-model", prompt_tokens=10, completion_tokens=0)

    rc = cli.main(
        [
            "session",
            "--resume",
            "--scripted",
            "--no-live",
            "--session-id",
            session_id,
            "--checkpoint-db",
            str(db_path),
        ]
    )
    err = capsys.readouterr().err

    # (a) it suspended, loudly, with the remedy — exit 2 is this CLI's "refused, not crashed".
    assert rc == 2
    assert "SUSPENDED" in err
    assert "coach session --resume" in err

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = build_session_graph(demo, checkpointer=checkpointer)
        state = resumable_session_state(graph, session_id)
        # (b) THE ADR 0005 clause: no zero-evidence `failed` question was manufactured.
        assert len(state["transcript"]) == 1
        assert [item["stop_reason"] for item in state["transcript"]] == ["resolved"]
        # (c) suspended, not completed and not aborted.
        assert state["status"] == "active"

    # (d) with the budget restored the same Session id resumes and completes, keeping Q1.
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "2500000")
    rc = cli.main(
        [
            "session",
            "--resume",
            "--scripted",
            "--no-live",
            "--session-id",
            session_id,
            "--checkpoint-db",
            str(db_path),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = build_session_graph(demo, checkpointer=checkpointer)
        state = resumable_session_state(graph, session_id)
        assert state["status"] == "complete"
        assert len(state["transcript"]) > 1
        assert state["transcript"][0]["stop_reason"] == "resolved"
    assert "(complete)" in out


def test_session_ledger_rows_carry_the_session_id(tmp_path, monkeypatch):
    # AC: `coach usage` shows per-session rows — which needs attribution on the rows themselves.
    # This pins the ContextVar surviving into langgraph's node execution, end to end.
    _tmp_ledger(monkeypatch, tmp_path)

    class _Recording(_ProviderDemoClient):
        def chat_json(self, *args, **kwargs):
            usage.record_usage("mimo", "test-model", prompt_tokens=3, completion_tokens=1)
            return super().chat_json(*args, **kwargs)

    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _Recording())

    rc = cli.main(
        [
            "session",
            "--scripted",
            "--no-live",
            "--max-questions",
            "1",
            "--session-id",
            "attributed",
            "--checkpoint-db",
            str(tmp_path / "c.sqlite"),
        ]
    )

    assert rc == 0
    per_session = usage.sessions_for_day()
    assert set(per_session) == {"attributed"}  # nothing escaped the scope into the "" bucket
    assert per_session["attributed"] > 0


def test_usage_command_shows_per_session_rows(tmp_path, monkeypatch, capsys):
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    with usage.session_scope("interview-42"):
        usage.record_usage("mimo", "test-model", prompt_tokens=1200, completion_tokens=300)
    usage.record_usage("mimo", "test-model", prompt_tokens=40, completion_tokens=10)

    assert cli.main(["usage"]) == 0

    out = capsys.readouterr().out
    assert "interview-42" in out
    assert "1,500" in out
    assert "unattributed" in out  # bench/forge/one-off spend stays honestly separate
    # The per-run ceiling is derived, so the line has to show the arithmetic (calls x tokens/call),
    # not a bare number no reader could check.
    assert f"{usage.session_token_budget(max_questions=5, max_turns=DEFAULT_MAX_TURNS):,}" in out
    assert f"{usage.worst_case_session_calls(5, DEFAULT_MAX_TURNS)} worst-case provider calls" in out
    assert str(usage.daily_question_cap()) in out
    # "per id", not "per run" — an id is reused, which is why the rail measures a delta instead.
    assert "Per Session id today (all runs on that id)" in out


# --- R-25 remediation: the rail must bound THIS RUN, keep evidence, and be resumable -------------


class _MeteredDemoClient(_ProviderDemoClient):
    """Bills the ledger on every provider call, so a Session's spend grows as it runs."""

    tokens_per_call = 100

    def chat_json(self, *args, **kwargs):
        usage.record_usage("mimo", "test-model", prompt_tokens=self.tokens_per_call, completion_tokens=0)
        return super().chat_json(*args, **kwargs)


def _session_argv(session_id, db_path, *extra, questions="1"):
    return [
        "session",
        "--scripted",
        "--no-live",
        "--max-questions",
        questions,
        "--session-id",
        session_id,
        "--checkpoint-db",
        str(db_path),
        *extra,
    ]


def _checkpoint_state(session_id, db_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    from interview_coach.supervisor import resumable_session_state

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = build_session_graph(DemoLLMClient(), checkpointer=checkpointer)
        return resumable_session_state(graph, session_id)


def test_every_interview_on_a_reused_session_id_gets_its_own_budget(tmp_path, monkeypatch, capsys):
    # THE per-session-id-per-UTC-day bug. `--session-id` defaults to the constant "local-session"
    # and the browser persists one id per Candidate, so a day's interviews share a name. Measuring
    # the name suspended the day's third interview for spending nothing of its own, and left the id
    # a dead end until 00:00 UTC. Reproduced here at the reviewer's exact ratio.
    _tmp_ledger(monkeypatch, tmp_path)
    db_path = tmp_path / "reused.sqlite"
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _MeteredDemoClient())

    # Run 1 with the rail effectively off, to measure what one of these Sessions actually costs.
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "10000000")
    assert cli.main(_session_argv("local-session", db_path)) == 0
    one_session = usage.session_run_spend("local-session")
    assert one_session > 0

    # Now size the rail at 2.5x one Session: comfortably more than any single run needs, and
    # comfortably LESS than three of them summed.
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", str(int(one_session * 2.5)))
    assert cli.main(_session_argv("local-session", db_path)) == 0
    assert cli.main(_session_argv("local-session", db_path)) == 0

    out, err = capsys.readouterr()
    assert "SUSPENDED" not in err
    assert out.count("(complete)") == 3
    # The id's day total really is past the budget — the rail simply is not measuring that number.
    assert usage.session_spend("local-session") > int(one_session * 2.5)


def test_a_session_that_crosses_the_ceiling_on_its_last_call_keeps_its_evidence(tmp_path, monkeypatch, capsys):
    # ADR 0006's scoring memory rides on this. The rail used to be evaluated on the FINAL stream
    # event too, so a Session that finished slightly over budget raised out of the `with` block:
    # exit 2, no Beta posteriors, no summary, no export — a plain abort of an interview that
    # produced real evidence, reported to the Candidate as a suspend.
    class _PlannerHeavy(_ProviderDemoClient):
        def chat_json(self, messages, response_model, *args, **kwargs):
            cost = 10_000 if response_model.__name__ == "StudyPlanDraft" else 10
            usage.record_usage("mimo", "test-model", prompt_tokens=cost, completion_tokens=0)
            return super().chat_json(messages, response_model, *args, **kwargs)

    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "1000")
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _PlannerHeavy())
    export = tmp_path / "session.md"
    ledger_db = tmp_path / "skills.json"

    rc = cli.main(
        _session_argv(
            "finishes",
            tmp_path / "done.sqlite",
            "--candidate",
            "kim",
            "--ledger-db",
            str(ledger_db),
            "--export-markdown",
            str(export),
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert usage.session_run_spend("finishes") > 1000, "the Session did not actually cross the ceiling"
    assert _checkpoint_state("finishes", tmp_path / "done.sqlite")["status"] == "complete"
    assert "(complete)" in out  # the summary printed
    assert export.exists()  # the export was written
    assert ledger_db.exists()  # and the Beta posteriors were persisted


def test_resuming_a_runaway_suspend_makes_progress_instead_of_looping(tmp_path, monkeypatch, capsys):
    # Measured before this fix: rc1=2 rc2=2 rc3=2, status=active, transcript stuck at 1 — three
    # resumes, zero progress, identical banner, and no remedy a web Candidate could ever perform.
    # A run's spend only grows, so this rail can never clear itself; the resume grants exactly one
    # more per-run budget and says so.
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "150")
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _MeteredDemoClient())
    db_path = tmp_path / "runaway.sqlite"

    assert cli.main(_session_argv("runaway", db_path, questions="2")) == 2
    assert "SUSPENDED" in capsys.readouterr().err

    resumes = []
    for _ in range(8):
        resumes.append(
            cli.main(
                [
                    "session",
                    "--resume",
                    "--scripted",
                    "--no-live",
                    "--session-id",
                    "runaway",
                    "--checkpoint-db",
                    str(db_path),
                ]
            )
        )
        if resumes[-1] == 0:
            break
    err = capsys.readouterr().err

    assert len(resumes) > 1, "the rail never fired again — this test is not exercising the loop"
    assert resumes[-1] == 0, f"the suspend never resumed to completion: {resumes}"
    assert "resuming clears the budget stop" in err
    assert "this resume grants" in err
    assert _checkpoint_state("runaway", db_path)["status"] == "complete"


def test_a_daily_exhaustion_suspend_says_the_wait_and_does_not_pretend_otherwise(tmp_path, monkeypatch, capsys):
    # The other rail: this one genuinely CANNOT be resumed until 00:00 UTC, and the message says so
    # rather than inviting a resume that provably loops.
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _MeteredDemoClient())
    db_path = tmp_path / "dry.sqlite"
    _suspend_after_first_question(_MeteredDemoClient(), db_path, "dry")
    usage.begin_session_run("dry")
    capsys.readouterr()

    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "10")
    usage.record_usage("mimo", "test-model", prompt_tokens=10, completion_tokens=0)
    rc = cli.main(
        ["session", "--resume", "--scripted", "--no-live", "--session-id", "dry", "--checkpoint-db", str(db_path)]
    )
    err = capsys.readouterr().err

    assert rc == 2
    assert "from now" in err  # a wait the reader can size, not a bare "00:00 UTC"
    assert "Resuming before then will suspend again" in err
    assert "with 1 question(s) resolved" in err  # the real count, never a blanket reassurance
    state = _checkpoint_state("dry", db_path)
    assert [item["stop_reason"] for item in state["transcript"]] == ["resolved"]
    assert state["status"] == "active"  # suspended, not aborted and not completed


def test_a_dead_quota_suspends_before_the_first_question(tmp_path, monkeypatch, capsys):
    # ADR 0005's addendum names insufficient_quota the DETECTION half and GH #80 the
    # session-behaviour half. Before this, a live Session with a dead quota degraded its Diagnostic,
    # then cascaded into zero-evidence `failed` questions and exited 0 with a Study Plan built from
    # nothing — verbatim the corruption the ADR's Why section describes.
    class _QuotaDead(_ProviderDemoClient):
        def chat_json(self, *args, **kwargs):
            usage.record_quota_exhausted("mimo")  # what llm.py latches on a real RateLimitError
            raise RuntimeError("Error code: 429 - insufficient_quota")

    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _QuotaDead())
    db_path = tmp_path / "quota.sqlite"

    rc = cli.main(_session_argv("no-quota", db_path, questions="3"))
    err = capsys.readouterr().err

    assert rc == 2
    assert "insufficient_quota" in err
    state = _checkpoint_state("no-quota", db_path)
    # Not one fabricated question: the Diagnostic degraded, and the rail suspended at the graph's
    # very first node boundary, before question_node ever ran.
    assert state is None or state["transcript"] == []
    assert state is None or state["status"] != "complete"


def test_a_dead_quota_mid_question_suspends_instead_of_cascading(tmp_path, monkeypatch, capsys):
    # The harder half: the quota dies once the graph is already running, so the exception DOES land
    # in question_node's `except Exception` net and one `failed` question is unavoidable without
    # editing supervisor.py. What the latch buys is that it stops there — one, not one per remaining
    # question, and exit 2 with no Study Plan instead of exit 0 with a fabricated one.
    class _QuotaAfterDiagnostic(_ProviderDemoClient):
        calls = 0

        def chat_json(self, *args, **kwargs):
            type(self).calls += 1
            if type(self).calls > 1:
                usage.record_quota_exhausted("mimo")
                raise RuntimeError("Error code: 429 - insufficient_quota")
            return super().chat_json(*args, **kwargs)

    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _QuotaAfterDiagnostic())
    db_path = tmp_path / "mid-quota.sqlite"

    rc = cli.main(_session_argv("mid-quota", db_path, questions="3"))
    err = capsys.readouterr().err

    assert rc == 2
    assert "insufficient_quota" in err
    state = _checkpoint_state("mid-quota", db_path)
    assert [item["stop_reason"] for item in state["transcript"]] == ["failed"]
    assert state["status"] != "complete"
    assert not state.get("study_plan")


def test_a_resume_retries_the_provider_once_and_re_suspends_if_it_is_still_dead(tmp_path, monkeypatch, capsys):
    # The quota latch cannot expire before 00:00 UTC and a suspended Session makes no calls, so
    # nothing but the resume can clear it. One real attempt, then the same honest suspend.
    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))
    monkeypatch.setattr(cli, "build_client", lambda settings: _MeteredDemoClient())
    db_path = tmp_path / "retry.sqlite"
    _suspend_after_first_question(_MeteredDemoClient(), db_path, "retry")
    usage.begin_session_run("retry")
    usage.record_quota_exhausted("mimo")
    capsys.readouterr()

    assert usage.quota_exhausted_today("mimo")
    rc = cli.main(
        ["session", "--resume", "--scripted", "--no-live", "--session-id", "retry", "--checkpoint-db", str(db_path)]
    )
    err = capsys.readouterr().err

    # The provider is healthy again in this run, so the retry succeeds and the Session finishes.
    assert rc == 0
    assert "retrying mimo after an insufficient_quota stop" in err
    assert not usage.quota_exhausted_today("mimo")


def test_the_derived_ceiling_is_silent_on_a_worst_case_session_and_still_stops_a_runaway(tmp_path, monkeypatch, capsys):
    # Both directions on the DEFAULT — no LLM_SESSION_TOKEN_BUDGET — because a ceiling that only
    # ever gets exercised at a test-shrunk value is not the ceiling that ships. The old 103,000
    # failed the first half of this by its own arithmetic: it counted one provider call per logical
    # step and priced each at the MEAN, so a Session of big prompts breached a rail it should never
    # have been able to reach.
    def brain(tokens_per_call):
        class _Billing(_ProviderDemoClient):
            def chat_json(self, *args, **kwargs):
                usage.record_usage("mimo", "test-model", prompt_tokens=tokens_per_call, completion_tokens=0)
                return super().chat_json(*args, **kwargs)

        return _Billing()

    _tmp_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(configured=True))

    # Compliant: a full 5-question interview where EVERY call is the size of the largest one ever
    # recorded in the ledger. A rail that fires here is a bug.
    monkeypatch.setattr(cli, "build_client", lambda settings: brain(usage.LARGEST_MEASURED_CALL_TOKENS))
    assert cli.main(_session_argv("compliant", tmp_path / "ok.sqlite", questions="5")) == 0
    assert "SUSPENDED" not in capsys.readouterr().err

    # Runaway: the same Session at 120k a call. Still stopped — and stopped by the derived default,
    # with no env var for the operator to have set in advance.
    monkeypatch.setattr(cli, "build_client", lambda settings: brain(120_000))
    assert cli.main(_session_argv("berserk", tmp_path / "runaway.sqlite", questions="5")) == 2
    err = capsys.readouterr().err
    assert "runaway, not a long interview" in err
    # And it was stopped well short of eating the day, which is what "nothing bounds a single
    # session" asked for.
    assert usage.session_run_spend("berserk") < usage.DEFAULT_DAILY_TOKEN_BUDGET // 2
