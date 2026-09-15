"""Free-tier hardening: the client-side daily token ledger and the noise-telemetry counters."""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from interview_coach import telemetry, usage
from interview_coach.usage import (
    DEFAULT_DAILY_QUESTION_CAP,
    DEFAULT_DAILY_TOKEN_BUDGET,
    HEAVIEST_MEASURED_SESSION_TOKENS,
    LARGEST_MEASURED_CALL_TOKENS,
    SESSION_SETUP_TOKENS,
    SESSION_TOKENS_PER_QUESTION,
    WORST_CASE_TOKENS_PER_CALL,
    begin_session_run,
    budget_stop_reason,
    clear_quota_exhausted,
    clear_run_rails_for_resume,
    daily_question_cap,
    daily_reset_hint,
    daily_token_budget,
    estimated_session_tokens,
    extend_budget_for_resume,
    question_cap_reason,
    questions_today,
    quota_exhausted_today,
    record_questions,
    record_questions_released,
    record_quota_exhausted,
    record_usage,
    remaining_today,
    reserve_questions,
    session_baseline,
    session_budget_guard,
    session_lifetime_spend,
    session_run_spend,
    session_scope,
    session_spend,
    session_token_budget,
    sessions_for_day,
    start_refusal_reason,
    token_identity,
    usage_for_day,
    utc_date,
    worst_case_question_calls,
    worst_case_session_calls,
    worst_case_session_tokens,
)


def test_record_and_aggregate_today(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=500, completion_tokens=100)
    record_usage("groq", "llama-3.3-70b-versatile", prompt_tokens=50, completion_tokens=10)

    totals = usage_for_day()
    assert totals["openai"] == {"prompt": 1500, "completion": 300, "total": 1800, "calls": 2}
    assert totals["groq"]["total"] == 60


def test_remaining_today_subtracts_spend_from_budget(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "1000")
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=700, completion_tokens=100)
    assert remaining_today("openai") == 200
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=900, completion_tokens=0)
    # Overspend clamps at zero: the rail reports "nothing left", never a negative allowance.
    assert remaining_today("openai") == 0


def test_the_daily_rail_counts_what_a_failover_billed_on_the_other_provider(tmp_path, monkeypatch):
    # LLMRouter bills the primary inside _create() and only THEN raises EmptyCompletionError, which
    # is_provider_failure() treats as an outage, so the fallback answers and bills the same logical
    # request; once the primary's breaker opens, only the fallback is billed at all. Either way the
    # spend is real, and a rail that reads one provider's bucket hands out a budget already spent.
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(estimated_session_tokens(1)))
    record_usage("groq", "llama-3.3-70b-versatile", prompt_tokens=SESSION_TOKENS_PER_QUESTION, completion_tokens=0)

    assert remaining_today("openai") == SESSION_SETUP_TOKENS
    assert start_refusal_reason("openai", questions=1) is not None


def test_other_days_do_not_count(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    stale = {
        "ts": "2001-01-01T00:00:00+00:00",
        "provider": "openai",
        "model": "m",
        "prompt_tokens": 999,
        "completion_tokens": 999,
    }
    ledger.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    assert usage_for_day() == {}
    assert usage_for_day("2001-01-01")["openai"]["total"] == 1998


def test_malformed_lines_are_skipped(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    record_usage("openai", "m", prompt_tokens=10, completion_tokens=5)
    with ledger.open("a", encoding="utf-8") as f:
        f.write("{not json}\n")
        f.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00"}) + "\n")  # missing fields
    record_usage("openai", "m", prompt_tokens=10, completion_tokens=5)
    assert usage_for_day()["openai"]["calls"] == 2


def test_a_half_written_token_row_is_skipped_whole(tmp_path, monkeypatch):
    # Tolerant, not lenient: a row missing one of its token fields is dropped entirely rather than
    # read as "0 of that field". Half-counting a corrupt line under-reports the day's spend, and the
    # daily budget rail is the only thing standing between a free tier and a dead quota.
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    truncated = {"ts": utc_date() + "T00:00:00+00:00", "provider": "openai", "model": "m", "completion_tokens": 5}
    ledger.write_text(json.dumps(truncated) + "\n", encoding="utf-8")

    assert usage_for_day() == {}
    assert sessions_for_day() == {}


def test_missing_ledger_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "nope.jsonl"))
    assert usage_for_day() == {}
    assert remaining_today("openai") == daily_token_budget()


def test_daily_budget_env_override(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "42")
    assert daily_token_budget() == 42
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "not-a-number")
    assert daily_token_budget() == DEFAULT_DAILY_TOKEN_BUDGET


# --- R-25: per-run budget + free-tier product caps ------------------------------------------------


def _stop(
    session_id: str = "sess-a",
    provider: str = "openai",
    *,
    questions_left: int = 4,
    questions_resolved: int = 1,
    max_questions: int = 5,
    max_turns: int = 4,
    session_complete: bool = False,
) -> str | None:
    """``budget_stop_reason`` with the boring arguments filled in."""
    return budget_stop_reason(
        session_id,
        provider,
        questions_left=questions_left,
        questions_resolved=questions_resolved,
        max_questions=max_questions,
        max_turns=max_turns,
        session_complete=session_complete,
    )


def _ledger(tmp_path, monkeypatch):
    """A private ledger with every rail's env var cleared — these read os.environ directly."""
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    for name in ("LLM_DAILY_TOKEN_BUDGET", "LLM_SESSION_TOKEN_BUDGET", "COACH_DAILY_QUESTION_CAP"):
        monkeypatch.delenv(name, raising=False)
    return ledger


# --- sizing the ceiling (the number the rail actually compares against) --------------------------


def test_the_call_model_matches_the_constants_it_restates(monkeypatch):
    # usage.py cannot import evaluator/interviewer/llm (they import IT), so it restates the retry
    # budgets that bound a Session's call count. This is the tripwire on that duplication: raise
    # JUDGE_MAX_RETRIES or _NATIVE_TOOL_ATTEMPTS and the ceiling silently stops covering the worst
    # case unless this test is updated too.
    import inspect

    from interview_coach.evaluator import JUDGE_MAX_RETRIES, PanelBudget
    from interview_coach.interviewer import _NATIVE_TOOL_ATTEMPTS
    from interview_coach.llm import _OpenAICompatibleClient

    monkeypatch.delenv("PANEL_MAX_ESCALATIONS_PER_QUESTION", raising=False)
    chat_json_retries = inspect.signature(_OpenAICompatibleClient.chat_json).parameters["max_retries"].default
    tool_retries = inspect.signature(_OpenAICompatibleClient.chat_with_tools).parameters["max_retries"].default

    assert usage.STRUCTURED_ATTEMPTS == 1 + chat_json_retries
    assert usage.STRUCTURED_ATTEMPTS == 1 + tool_retries
    assert usage.JUDGE_ATTEMPTS == 1 + JUDGE_MAX_RETRIES
    assert usage.NATIVE_TOOL_ATTEMPTS == _NATIVE_TOOL_ATTEMPTS
    assert usage.PANEL_ESCALATIONS_PER_QUESTION == PanelBudget.per_question().remaining


def test_the_worst_case_arithmetic_is_pinned():
    # Written out so the next person cannot quietly shave the ceiling: every term is a count of
    # PROVIDER calls, and a schema retry is a provider call that bills tokens.
    # NEW-06: the routed roles are doubled, because a failover bills a SECOND provider for the same
    # logical call. The judge is not — it is seated on a pinned client and cannot fail over (ADR
    # 0009a), so doubling it would loosen the rail for a case that cannot happen.
    #   per question (max_turns=4): 2x(2 seed-render + 3x6 follow-ups + 2 supervisor)
    #                               + 4x6 evaluations + 10 one panel            = 78
    #   per Session (max_questions=5): 2x2 Diagnostic + 5x78 + 2x2 Study Plan    = 394
    assert (usage.EVALUATION_CALLS, usage.PANEL_CALLS, usage.FOLLOW_UP_CALLS) == (6, 10, 6)
    assert worst_case_question_calls(4) == 78
    assert worst_case_session_calls(5, 4) == 394
    assert worst_case_session_tokens(5, 4) == 394 * WORST_CASE_TOKENS_PER_CALL
    assert worst_case_session_tokens(5, 4) == 1_063_800


def test_the_ceiling_counts_the_second_provider_a_failover_bills():
    # Routed roles (seed render, follow-ups, Supervisor) ride LLMRouter and can bill two providers
    # for one logical call; the judge is a pinned client (ADR 0009a) and never fails over, so
    # doubling its calls would loosen the runaway rail for a case that cannot happen. Splitting the
    # two is what stops a blanket 2x from being pinned by accident.
    routed = usage.SEED_RENDER_CALLS + 3 * usage.FOLLOW_UP_CALLS + usage.SUPERVISOR_CALLS
    pinned = 4 * usage.EVALUATION_CALLS + usage.PANEL_ESCALATIONS_PER_QUESTION * usage.PANEL_CALLS
    assert worst_case_question_calls(4) == 2 * routed + pinned
    assert usage.FAILOVER_PROVIDERS_PER_CALL == 2


def test_every_sizing_constant_still_follows_from_its_measurement():
    # The ledger is gitignored runtime state, so no test can re-read the three measurements. What a
    # test CAN pin is that everything derived from them still follows — which is the mutation that
    # actually matters: a bare `!= 5_200` would be a change detector, but a constant that no longer
    # follows from its measurement has silently re-sized a rail.
    import math

    rounding = usage.MEASUREMENT_ROUNDING
    up = lambda value: math.ceil(value / rounding) * rounding  # noqa: E731

    assert WORST_CASE_TOKENS_PER_CALL == up(LARGEST_MEASURED_CALL_TOKENS)
    assert SESSION_SETUP_TOKENS == up(usage.HEAVIEST_MEASURED_DIAGNOSTIC_TOKENS)
    heaviest_questions = HEAVIEST_MEASURED_SESSION_TOKENS - usage.HEAVIEST_MEASURED_DIAGNOSTIC_TOKENS
    assert SESSION_TOKENS_PER_QUESTION == up(heaviest_questions / 5)


def test_the_ceiling_is_bracketed_by_what_the_ledger_measured():
    # Above: a ceiling a real Session can reach fires on compliant behaviour, so the whole ceiling
    # must dwarf the heaviest Session ever measured.
    assert worst_case_session_tokens(5, 4) > 20 * HEAVIEST_MEASURED_SESSION_TOKENS
    # Below: a ceiling one Session cannot fit under twice over is not bounding anything, which is the
    # thing the issue asked for ("nothing bounds a single session"). Was `// 3` before NEW-06 added
    # the failover multiplier — the bracket loosens by exactly that factor and no more.
    assert worst_case_session_tokens(5, 4) < DEFAULT_DAILY_TOKEN_BUDGET // 2


def test_the_ceiling_scales_with_the_rails_the_session_declared():
    # A flat number is loose exactly where the risk is. A 1-question Session must not be handed a
    # 5-question ceiling, and a legitimately long interview must not be suspended for being long.
    assert worst_case_session_tokens(1, 4) < worst_case_session_tokens(5, 4)
    assert worst_case_session_tokens(5, 2) < worst_case_session_tokens(5, 4)
    assert worst_case_session_tokens(0, 4) == (usage.DIAGNOSTIC_CALLS + usage.STUDY_PLAN_CALLS) * (
        WORST_CASE_TOKENS_PER_CALL
    )
    # max_turns is a safety CAP, so it is never below one turn even if a caller passes nonsense.
    assert worst_case_question_calls(0) == worst_case_question_calls(1)


def test_the_runaway_rail_is_sized_on_the_estimate_the_session_was_admitted_on(monkeypatch):
    # NEW-09: the start gate admits a Session on estimated_session_tokens(); the rail that calls it a
    # runaway must price it with the SAME cost model, not with one an order of magnitude larger. The
    # gap was measured at ~29x before the failover multiplier (NEW-06) and ~40x after it, which put a
    # single 10-question web Candidate's ceiling at 85% of the whole day.
    monkeypatch.delenv("LLM_SESSION_TOKEN_BUDGET", raising=False)
    for questions in (1, 3, 10):
        admitted = estimated_session_tokens(questions)
        ceiling = session_token_budget(max_questions=questions, max_turns=4)
        assert ceiling <= usage.session_ceiling_multiple(4) * admitted, (
            f"{questions}q: admitted at ~{admitted:,}, runaway rail at ~{ceiling:,} "
            f"({ceiling / admitted:.1f}x the estimate it was admitted on)"
        )
    # And no single Candidate is handed a majority of the day (the web caps max_questions at 10).
    assert session_token_budget(max_questions=10, max_turns=4) < DEFAULT_DAILY_TOKEN_BUDGET // 4


def test_the_ceiling_multiple_is_derived_from_the_measured_constants_not_chosen():
    # Both factors are measurements, so the number moves when the measurements do — and a future
    # tuner has to change a constant with a ledger behind it rather than a magic multiplier.
    assert usage.compliant_question_calls(4) == 15  # 1 seed + 4 judgments + 3x2 follow-ups + 3 panel + 1 supervisor
    assert usage.CALL_SIZE_INFLATION == pytest.approx(2_700 * 16 / 26_866)
    assert usage.session_ceiling_multiple(4) == 9
    # Proportional to the rails the Session declared, which is what the worst-case model argues for.
    assert [usage.session_ceiling_multiple(t) for t in (1, 2, 4, 8)] == [4, 5, 9, 15]


def test_the_default_rail_suspends_a_session_spending_ten_times_its_admitted_estimate(tmp_path, monkeypatch):
    # No LLM_SESSION_TOKEN_BUDGET: the ceiling that SHIPS, not a test-shrunk stand-in. Every other
    # runaway test opts out of the default, so nothing in the suite exercised the real one.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.delenv("LLM_SESSION_TOKEN_BUDGET", raising=False)
    spent = 10 * estimated_session_tokens(5)  # 270,000 on a Session admitted at ~27,000
    begin_session_run("sess-a")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=spent, completion_tokens=0)

    reason = _stop(session_id="sess-a")

    assert reason is not None
    assert "runaway, not a long interview" in reason
    # ADR 0005's third category: suspend-and-resume, never a failed question, and the remedy is one
    # a web Candidate can perform.
    assert "Suspending with 1 question(s) resolved" in reason
    assert "Resume this Session to continue" in reason


def test_session_budget_env_override(monkeypatch):
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "77")
    assert session_token_budget(max_questions=5, max_turns=4) == 77
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "not-a-number")
    # NEW-09: the default the override falls back to is the ceiling sized on the admitted estimate,
    # not the retry-storm worst case — which was ~40x it and 85% of the day at max_questions=10.
    default = usage.session_ceiling_multiple(4) * estimated_session_tokens(5)
    assert session_token_budget(max_questions=5, max_turns=4) == default


def test_daily_question_cap_env_override(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "7")
    assert daily_question_cap() == 7
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "not-a-number")
    assert daily_question_cap() == DEFAULT_DAILY_QUESTION_CAP


def test_estimated_session_tokens_counts_setup_once():
    assert estimated_session_tokens(3) == SESSION_SETUP_TOKENS + 3 * SESSION_TOKENS_PER_QUESTION
    # Mid-session there is no second Diagnostic to pay for, so the remaining-cost estimate drops it.
    assert estimated_session_tokens(3, include_setup=False) == 3 * SESSION_TOKENS_PER_QUESTION
    assert estimated_session_tokens(0, include_setup=False) == 0
    # A negative "questions left" is a caller slip, never a negative cost.
    assert estimated_session_tokens(-2, include_setup=False) == 0


def test_the_start_estimate_brackets_the_measured_sessions():
    # The asymmetry of a start gate: refusing to start is free, dying mid-Session is not, so the
    # default 5-question estimate must cover the heaviest Session ever measured in the ledger...
    assert estimated_session_tokens(5) >= HEAVIEST_MEASURED_SESSION_TOKENS
    # ...but over-estimating is not free either: an inflated estimate refuses Sessions the day could
    # comfortably have paid for. Stay within 2x of the heaviest thing actually observed.
    assert estimated_session_tokens(5) <= 2 * HEAVIEST_MEASURED_SESSION_TOKENS
    # And it is emphatically NOT the ceiling: they answer opposite questions.
    assert estimated_session_tokens(5) < worst_case_session_tokens(5, 4)


# --- attribution and the mixed-row ledger --------------------------------------------------------


def test_session_scope_attributes_ledger_rows(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=100, completion_tokens=10)
    record_usage("openai", "m", prompt_tokens=5, completion_tokens=1)  # a bench/forge one-off

    assert sessions_for_day() == {"sess-a": 110, "": 6}
    assert session_spend("sess-a") == 110
    assert session_spend("never-ran") == 0
    # Attribution must not disturb the per-provider view the daily rail reads.
    assert usage_for_day()["openai"]["total"] == 116


def test_session_scope_restores_the_previous_attribution(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    with session_scope("outer"):
        with session_scope("inner"):
            record_usage("openai", "m", prompt_tokens=1, completion_tokens=0)
        record_usage("openai", "m", prompt_tokens=2, completion_tokens=0)

    assert sessions_for_day() == {"inner": 1, "outer": 2}


def test_non_token_rows_are_invisible_to_every_token_reader(tmp_path, monkeypatch):
    # Four row kinds share one file. The mixed-row design rests on none of them being mistaken for
    # spend — a `session_run` baseline read as tokens would corrupt the very rail it feeds.
    _ledger(tmp_path, monkeypatch)
    record_questions("id-1", 3)
    record_questions("id-1", 2)
    record_questions("id-2", 4)
    begin_session_run("sess-a")
    record_quota_exhausted("openai")
    clear_quota_exhausted("openai")

    assert questions_today("id-1") == 5
    assert questions_today("id-2") == 4
    assert questions_today("nobody") == 0
    assert usage_for_day() == {}
    assert sessions_for_day() == {}
    assert session_lifetime_spend("sess-a") == 0
    assert session_run_spend("sess-a") == 0


def test_only_rows_marked_as_questions_are_counted(tmp_path, monkeypatch):
    # The cap counts `kind: "questions"` rows, not "any row carrying an identity". One ledger file
    # holds several row shapes, so the marker — not a coincidence of which keys happen to be present
    # — is what makes a row a question reservation.
    ledger = _ledger(tmp_path, monkeypatch)
    unmarked = {"ts": utc_date() + "T00:00:00+00:00", "identity": "id-1", "questions": 99}
    ledger.write_text(json.dumps(unmarked) + "\n", encoding="utf-8")

    assert questions_today("id-1") == 0
    record_questions("id-1", 2)
    assert questions_today("id-1") == 2


def test_question_rows_from_another_day_do_not_count(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path, monkeypatch)
    stale = {"ts": "2001-01-01T00:00:00+00:00", "kind": "questions", "identity": "id-1", "questions": 9}
    ledger.write_text(json.dumps(stale) + "\n", encoding="utf-8")

    assert questions_today("id-1") == 0
    assert questions_today("id-1", day="2001-01-01") == 9


def test_token_identity_is_stable_and_never_the_secret():
    assert token_identity("") == "anonymous"
    assert token_identity("   ") == "anonymous"
    secret = "s3cret-token"
    assert token_identity(secret) == token_identity(secret)
    assert secret not in token_identity(secret)
    assert token_identity(secret) != token_identity("other-token")
    # Truncated, not the full digest: short enough to eyeball in a ledger, long enough not to collide.
    assert len(token_identity(secret)) == 16


# --- per-RUN accounting: the rail must bound THIS run, not the id's history ----------------------


def test_each_run_on_a_reused_id_gets_its_own_budget(tmp_path, monkeypatch):
    # THE bug this rail had. `--session-id` defaults to the constant "local-session" and the browser
    # persists one id per Candidate, so a day's interviews share a name. Measuring the NAME suspends
    # the day's third interview for spending nothing of its own, and bricks the id until 00:00 UTC.
    _ledger(tmp_path, monkeypatch)
    for _ in range(3):
        begin_session_run("local-session")
        with session_scope("local-session"):
            record_usage("openai", "m", prompt_tokens=200, completion_tokens=0)
        assert session_run_spend("local-session") == 200

    # The id's own history is still there and still reported — it is just not what the rail reads.
    assert session_spend("local-session") == 600
    assert session_lifetime_spend("local-session") == 600
    assert session_baseline("local-session") == 400


def test_a_run_with_no_baseline_row_is_measured_from_its_first_token(tmp_path, monkeypatch):
    # A Session checkpointed before this rail existed has no baseline. Measuring it from zero
    # over-counts rather than under-counts, and for a spend rail that is the safe direction.
    _ledger(tmp_path, monkeypatch)
    with session_scope("legacy"):
        record_usage("openai", "m", prompt_tokens=700, completion_tokens=0)

    assert session_baseline("legacy") == 0
    assert session_run_spend("legacy") == 700


def test_a_run_spans_the_utc_rollover(tmp_path, monkeypatch):
    # Suspended at 23:59, resumed at 00:01 — one run. Day-scoping the spend would hand a runaway a
    # whole fresh budget at midnight for free.
    ledger = _ledger(tmp_path, monkeypatch)
    yesterday = [
        {"ts": "2001-01-01T22:00:00+00:00", "kind": "session_run", "session": "s", "baseline": 0},
        {
            "ts": "2001-01-01T23:59:00+00:00",
            "provider": "openai",
            "model": "m",
            "session": "s",
            "prompt_tokens": 400,
            "completion_tokens": 0,
        },
    ]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in yesterday), encoding="utf-8")

    assert session_run_spend("s") == 400
    assert session_spend("s") == 0  # today's per-id view honestly shows nothing


def test_the_run_spend_never_goes_negative(tmp_path, monkeypatch):
    # A baseline is a snapshot of the id's lifetime spend, so lifetime cannot normally fall below it
    # — unless the ledger is rotated, truncated or repointed under a live Session. That is precisely
    # when the rail must not disarm itself: a negative "spent" reads as infinite headroom, and the
    # runaway the rail exists to stop would run unbounded.
    ledger = _ledger(tmp_path, monkeypatch)
    stale_baseline = {"ts": utc_date() + "T00:00:00+00:00", "kind": "session_run", "session": "s", "baseline": 5_000}
    ledger.write_text(json.dumps(stale_baseline) + "\n", encoding="utf-8")
    with session_scope("s"):
        record_usage("openai", "m", prompt_tokens=100, completion_tokens=0)

    assert session_run_spend("s") == 0


def test_reading_the_run_spend_never_forgives_anything(tmp_path, monkeypatch):
    # A resume re-reads this number; if reading it re-baselined, every resume would silently hand
    # out a fresh full budget and the rail would bound nothing at all.
    _ledger(tmp_path, monkeypatch)
    begin_session_run("s")
    with session_scope("s"):
        record_usage("openai", "m", prompt_tokens=500, completion_tokens=0)

    assert session_run_spend("s") == 500
    assert session_run_spend("s") == 500
    assert session_baseline("s") == 0


# --- the stop reasons ----------------------------------------------------------------------------


def test_budget_stop_reason_is_silent_while_comfortably_in_budget(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    begin_session_run("sess-a")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=1000, completion_tokens=100)

    assert _stop() is None


def test_the_runaway_reason_measures_this_run_not_the_id(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "1000")
    with session_scope("sess-a"):  # a previous run under the same id
        record_usage("openai", "m", prompt_tokens=5000, completion_tokens=0)
    begin_session_run("sess-a")
    assert _stop() is None, "the new run inherited the old run's spend"

    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=900, completion_tokens=100)
    reason = _stop()

    assert reason is not None
    assert "LLM_SESSION_TOKEN_BUDGET" in reason
    assert "~1,000 tokens on this run" in reason  # this run's 1,000, not the id's 6,000
    # Suspend-and-resume (ADR 0005), and the resume is one a web Candidate can actually perform —
    # no env var to edit. `extend_budget_for_resume` is what makes that sentence true.
    assert "Resume this Session to continue" in reason


def test_budget_stop_reason_fires_on_daily_exhaustion(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "2000")
    begin_session_run("sess-a")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=1900, completion_tokens=100)

    # Within the per-run ceiling, but the day cannot fund even one more question.
    reason = _stop(questions_left=1)
    assert reason is not None
    assert "00:00 UTC" in reason
    # Honest about the one remedy that works: this rail clears on the clock, not on a resume.
    assert "Resuming before then will suspend again" in reason
    # Nothing left to ask: the Session is about to finish anyway, so there is nothing to suspend.
    assert _stop(questions_left=0) is None


def test_exactly_enough_budget_for_the_rest_is_not_a_breach(tmp_path, monkeypatch):
    # Boundary: "enough" means enough. A Session is never suspended for a shortfall of zero.
    _ledger(tmp_path, monkeypatch)
    spent, questions_left = 500, 2
    needed = estimated_session_tokens(questions_left, include_setup=False)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(spent + needed))
    begin_session_run("sess-a")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=spent, completion_tokens=0)

    assert _stop(questions_left=questions_left) is None
    # One token less and it is a breach.
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(spent + needed - 1))
    assert _stop(questions_left=questions_left) is not None


def test_every_stop_and_refusal_says_how_long_the_wait_is(tmp_path, monkeypatch):
    # "resets at 00:00 UTC" is not a wait time, and a suspend whose remedy the reader cannot size is
    # a stall wearing a suspend's clothes.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "0")
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "0")
    reasons = [
        _stop(questions_left=1),
        start_refusal_reason("openai", questions=1),
        question_cap_reason("id-1", questions=1),
    ]

    assert all(reason is not None and "from now" in reason for reason in reasons)
    assert daily_reset_hint(datetime(2026, 8, 1, 21, 30, tzinfo=UTC)) == (
        "The daily allowance resets at 00:00 UTC, ~2h30m from now."
    )


def test_the_stop_reasons_report_the_questions_actually_resolved(tmp_path, monkeypatch):
    # The old wording promised "the questions resolved so far are kept" on a Session with none.
    # Every reason now carries the real count, so it cannot misdiagnose.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "1")
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "0")
    begin_session_run("sess-a")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=10, completion_tokens=0)

    assert "with 0 question(s) resolved" in (_stop(questions_resolved=0) or "")
    monkeypatch.delenv("LLM_SESSION_TOKEN_BUDGET")
    assert "with 3 question(s) resolved" in (_stop(questions_resolved=3, questions_left=2) or "")


def test_a_completed_session_is_never_suspended(tmp_path, monkeypatch):
    # ADR 0006's scoring memory rides on this. A suspend raised on the final stream event unwinds
    # the driver before save_posteriors, the summary and the export — a plain abort of a Session
    # that produced real evidence, reported as a suspend. Every rail stands down at COMPLETE.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "1")
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "0")
    begin_session_run("done")
    with session_scope("done"):
        record_usage("openai", "m", prompt_tokens=10_000, completion_tokens=0)
    record_quota_exhausted("openai")

    assert _stop(session_id="done", questions_left=0, session_complete=False) is not None
    assert _stop(session_id="done", questions_left=0, session_complete=True) is None
    assert _stop(session_id="done", questions_left=2, session_complete=True) is None


def test_start_refusal_fires_only_when_the_day_cannot_fund_the_session(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(estimated_session_tokens(2) + 1))

    assert start_refusal_reason("openai", questions=2) is None
    record_usage("openai", "m", prompt_tokens=2, completion_tokens=0)
    reason = start_refusal_reason("openai", questions=2)
    assert reason is not None
    assert "00:00 UTC" in reason  # the remedy, not just the refusal
    # NEW-06 inverts what this used to pin. LLM_DAILY_TOKEN_BUDGET is ONE scalar and a failover bills
    # a second provider for the same logical call, so another provider's spend IS this provider's
    # problem — and once the primary's breaker opens, only the fallback is billed at all, which a
    # per-provider rail would never see.
    assert start_refusal_reason("groq", questions=2) is not None


def test_question_cap_reason_names_the_env_var(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "5")

    assert question_cap_reason("id-1", questions=5) is None
    record_questions("id-1", 1)
    reason = question_cap_reason("id-1", questions=5)
    assert reason is not None
    assert "COACH_DAILY_QUESTION_CAP" in reason
    assert question_cap_reason("id-2", questions=5) is None  # per identity, not global


# --- insufficient_quota: ADR 0005's detection half, wired to its session-behaviour half ----------


def test_a_latched_quota_suspends_instead_of_failing_the_rest(tmp_path, monkeypatch):
    # Without this the Session falls into question_node's `except Exception`, records zero-evidence
    # `failed` questions and exits 0 with a Study Plan built from nothing — verbatim the corruption
    # ADR 0005's Why section describes.
    _ledger(tmp_path, monkeypatch)
    assert _stop() is None
    record_quota_exhausted("openai")
    reason = _stop()

    assert reason is not None
    assert "insufficient_quota" in reason
    assert "00:00 UTC" in reason
    assert "Resuming re-tries the provider once" in reason
    # Per provider: a dead OpenAI quota says nothing about Groq's.
    assert _stop(provider="groq") is None


def test_the_quota_latch_clears_on_any_later_sign_of_life(tmp_path, monkeypatch):
    # It cannot expire on its own before 00:00 UTC, and a suspended Session makes no calls, so
    # nothing would ever clear it — the resume ADR 0005 promises would loop forever.
    _ledger(tmp_path, monkeypatch)
    record_quota_exhausted("openai")
    assert quota_exhausted_today("openai")

    clear_quota_exhausted("openai")  # what a resume does
    assert not quota_exhausted_today("openai")

    record_quota_exhausted("openai")
    assert quota_exhausted_today("openai")
    record_usage("openai", "m", prompt_tokens=1, completion_tokens=0)  # a call that succeeded
    assert not quota_exhausted_today("openai")


def test_the_quota_latch_is_scoped_to_its_day(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path, monkeypatch)
    stale = {"ts": "2001-01-01T00:00:00+00:00", "kind": "quota_exhausted", "provider": "openai"}
    ledger.write_text(json.dumps(stale) + "\n", encoding="utf-8")

    assert not quota_exhausted_today("openai")
    assert quota_exhausted_today("openai", day="2001-01-01")


def test_a_dead_quota_refuses_a_fresh_start(tmp_path, monkeypatch):
    # The day counter is our own guess at the provider's allowance; the provider saying
    # insufficient_quota is not a guess. Starting into it burns a Diagnostic to learn nothing.
    _ledger(tmp_path, monkeypatch)
    assert start_refusal_reason("openai", questions=1) is None
    record_quota_exhausted("openai")
    reason = start_refusal_reason("openai", questions=1)

    assert reason is not None
    assert "insufficient_quota" in reason


# --- making a suspend genuinely resumable --------------------------------------------------------


def test_extend_budget_for_resume_only_forgives_an_actual_breach(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "1000")
    begin_session_run("s")
    with session_scope("s"):
        record_usage("openai", "m", prompt_tokens=999, completion_tokens=0)

    assert extend_budget_for_resume("s", max_questions=5, max_turns=4) is None
    with session_scope("s"):
        record_usage("openai", "m", prompt_tokens=1, completion_tokens=0)
    assert extend_budget_for_resume("s", max_questions=5, max_turns=4) == 1000
    # And the grant is exactly one budget, not amnesty: the rail re-arms from here.
    assert session_run_spend("s") == 0
    assert _stop(session_id="s") is None


def test_a_resume_breaks_the_loop_the_per_run_ceiling_would_otherwise_create(tmp_path, monkeypatch):
    # A run's spend only grows, so this rail can never clear itself: without the grant, every resume
    # re-trips at the first node boundary forever — the stall ADR 0005 forbids, and one a web
    # Candidate cannot escape because they cannot edit LLM_SESSION_TOKEN_BUDGET.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "500")
    begin_session_run("s")
    with session_scope("s"):
        record_usage("openai", "m", prompt_tokens=600, completion_tokens=0)
    assert _stop(session_id="s") is not None

    note = clear_run_rails_for_resume("s", "openai", max_questions=5, max_turns=4)

    assert note is not None
    assert "~600 tokens" in note and "~500 more" in note
    assert _stop(session_id="s") is None


def test_a_resume_also_retries_a_dead_quota_and_says_which(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch)
    record_quota_exhausted("openai")

    note = clear_run_rails_for_resume("s", "openai", max_questions=5, max_turns=4)

    assert note is not None
    assert "retrying openai" in note
    assert _stop(session_id="s") is None
    # Nothing left to clear the second time round.
    assert clear_run_rails_for_resume("s", "openai", max_questions=5, max_turns=4) is None


def test_a_resume_grants_its_own_session_one_retry_and_nobody_else(tmp_path, monkeypatch):
    # NEW-05. The grant is one human saying "try again" about their own interview, not a fact about
    # the account. Global, it converted a clean refusal into broken interviews: A resumes, B/C/D sail
    # through the start gate, each burns a Diagnostic to rediscover the same dead quota — and the
    # first of them re-latches it, cancelling A's attempt too.
    _ledger(tmp_path, monkeypatch)
    record_quota_exhausted("openai")

    note = clear_run_rails_for_resume("sess-a", "openai", max_questions=5, max_turns=4)

    assert note is not None and "retrying openai" in note
    assert _stop(session_id="sess-a") is None  # A still gets its one real attempt
    assert _stop(session_id="sess-b") is not None  # B's suspend is untouched
    assert start_refusal_reason("openai", questions=1) is not None  # and a fresh start stays refused
    assert quota_exhausted_today("openai")
    assert not quota_exhausted_today("openai", session="sess-a")


def test_the_granted_retry_is_one_attempt_and_a_billed_call_revives_everyone(tmp_path, monkeypatch):
    # The two halves the scoping must not break: the grant is spent by the attempt that re-latches,
    # and a call that actually billed tokens IS a fact about the account, so it clears for everybody.
    _ledger(tmp_path, monkeypatch)
    record_quota_exhausted("openai")
    clear_run_rails_for_resume("sess-a", "openai", max_questions=5, max_turns=4)

    record_quota_exhausted("openai")  # what llm.py latches when the granted attempt dies again
    assert _stop(session_id="sess-a") is not None

    clear_run_rails_for_resume("sess-a", "openai", max_questions=5, max_turns=4)
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=1, completion_tokens=0)
    assert _stop(session_id="sess-b") is None
    assert start_refusal_reason("openai", questions=1) is None


def test_a_resume_does_not_clear_the_daily_rail(tmp_path, monkeypatch):
    # The daily ledger rail is arithmetic over the day, not a latch on this run — it clears at
    # 00:00 UTC whether anyone resumes or not. Forgiving it here would let a resume loop spend the
    # provider's real allowance to zero one call at a time.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "10")
    begin_session_run("s")
    record_usage("openai", "m", prompt_tokens=10, completion_tokens=0)

    assert clear_run_rails_for_resume("s", "openai", max_questions=5, max_turns=4) is None
    assert _stop(session_id="s", questions_left=1) is not None


# --- the guard both surfaces install --------------------------------------------------------------


def test_the_guard_reads_the_state_keys_the_graph_actually_sets(tmp_path, monkeypatch):
    # One factory for the CLI and the web, so the two surfaces cannot disagree about when a Session
    # suspends. The subtraction is the load-bearing part: questions already resolved are already
    # paid for, and charging for them again suspends a Session that can afford the rest of itself.
    _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(estimated_session_tokens(1, include_setup=False)))
    begin_session_run("s")
    guard = session_budget_guard("s", "openai", max_turns=4, complete_status="complete")

    assert guard({"max_questions": 3, "question_count": 2, "status": "active"}) is None
    assert guard({"max_questions": 3, "question_count": 0, "status": "active"}) is not None
    assert guard({"max_questions": 3, "question_count": 0, "status": "complete"}) is None


def test_telemetry_incr_snapshot_delta_reset():
    telemetry.reset()
    before = telemetry.snapshot()
    telemetry.incr("sanitizer.test_event")
    telemetry.incr("sanitizer.test_event")
    telemetry.incr("evaluator.other", 3)
    after = telemetry.snapshot()
    assert after["sanitizer.test_event"] == 2
    assert telemetry.delta(before, after) == {"sanitizer.test_event": 2, "evaluator.other": 3}
    # Unchanged keys stay out of the delta — the bench section only shows what THIS run moved.
    assert telemetry.delta(after, after) == {}
    telemetry.reset()
    assert telemetry.snapshot() == {}


# --- M0a / F1: accounting health ------------------------------------------------------------------
#
# The rails above are arithmetic over the ledger file. Every test in this section exists because
# arithmetic over a file nobody is writing reads as "spent nothing" — the most permissive answer
# there is, from the least reliable input. Two fault shapes, deliberately kept apart:
#
#   ledger path is a DIRECTORY  -> the ledger cannot be appended, its sidecar (a sibling file) can.
#                                  This is the realistic container shape: writes fail, the directory
#                                  around them does not.
#   ledger parent is a FILE     -> neither the ledger nor the sidecar can be written. The worst case,
#                                  pinned separately because it is the one the latch cannot outlive.


def _broken_ledger(tmp_path, monkeypatch):
    """A ledger path that cannot be appended to, in a directory that can still hold the sidecar."""
    ledger = tmp_path / "usage-ledger.jsonl"
    ledger.mkdir()
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    return ledger


def test_a_healthy_ledger_blocks_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "usage-ledger.jsonl"))
    assert usage.check_ledger_writable() is None
    assert usage.accounting_fault() is None
    assert usage.accounting_block_reason() is None
    assert usage.accounting_gate() is None


def test_the_probe_creates_the_ledger_rather_than_asserting_the_mode_bits(tmp_path, monkeypatch):
    # `os.access` answers a question about permissions; the rail's question is "will the next append
    # work", which only an append answers. Creating the file is the honest side effect of asking.
    ledger = tmp_path / "nested" / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    assert usage.check_ledger_writable() is None
    assert ledger.exists()
    assert ledger.read_text(encoding="utf-8") == ""


def test_an_unwritable_path_blocks_before_anything_is_spent(tmp_path, monkeypatch):
    # AC 3. The pre-call half: the condition is visible, it names the remedy, and it says out loud
    # that nothing is unaccounted for — which is the whole reason it is a different state from the
    # post-call one below.
    _broken_ledger(tmp_path, monkeypatch)

    reason = usage.check_ledger_writable()
    assert reason is not None
    assert "cannot be written" in reason
    assert "COACH_USAGE_LEDGER" in reason
    assert "Nothing is unaccounted for yet" in reason
    # ...and it reaches both rails, so neither surface can start or continue a metered Session.
    assert usage.start_refusal_reason("openai", questions=1) == reason
    assert _stop(questions_left=1) == reason


def test_the_start_gate_refuses_an_unwritable_ledger_before_the_quota_and_budget_rails(tmp_path, monkeypatch):
    # Precedence matters: with the ledger broken, `remaining_today` reports a FULL budget, so the
    # two rails below would both wave the Session through on a number they cannot know.
    _broken_ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "1")  # would refuse on its own, with other wording

    refusal = usage.start_refusal_reason("openai", questions=1)
    assert refusal is not None
    assert "Usage accounting is unavailable" in refusal
    assert "00:00 UTC" not in refusal  # not a scarcity story; waiting for the reset fixes nothing


def test_a_running_session_suspends_on_an_unwritable_ledger(tmp_path, monkeypatch):
    _broken_ledger(tmp_path, monkeypatch)
    guard = session_budget_guard("s", "openai", max_turns=4, complete_status="complete")

    reason = guard({"max_questions": 3, "question_count": 1, "status": "active"})
    assert reason is not None
    assert "Usage accounting is unavailable" in reason


def test_a_completed_session_is_not_suspended_by_a_broken_ledger(tmp_path, monkeypatch):
    # The same carve-out the budget rail already has, and for a stronger reason here: at COMPLETE the
    # only spend left is one Study Plan call, which the call-boundary gate refuses on its own. Firing
    # here would discard a whole interview's evidence to prevent a call already prevented.
    _broken_ledger(tmp_path, monkeypatch)
    guard = session_budget_guard("s", "openai", max_turns=4, complete_status="complete")

    assert guard({"max_questions": 3, "question_count": 3, "status": "complete"}) is None


def test_a_billed_call_whose_row_cannot_be_written_is_never_counted_as_zero(tmp_path, monkeypatch):
    # AC 4, the core of this slice. The provider answered and charged us; only the bookkeeping
    # failed. The tokens are parked, the condition says UNRECONCILED, and it names what it holds.
    ledger = _broken_ledger(tmp_path, monkeypatch)

    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200)  # must not raise

    fault = usage.accounting_fault()
    assert fault is not None
    assert "UNRECONCILED" in fault
    assert "1 provider call" in fault
    assert "~1,200 token(s)" in fault  # the spend is stated, not rounded away
    parked = usage.ledger_fault_path(ledger)
    assert parked.exists()
    held = json.loads(parked.read_text(encoding="utf-8").splitlines()[0])
    assert held["billed"] is True
    assert held["entry"]["prompt_tokens"] == 1000


def test_a_bookkeeping_row_that_cannot_be_written_says_no_spend_is_unaccounted(tmp_path, monkeypatch):
    # The other side of the pre/post distinction. A `questions` reservation is written BEFORE any
    # call, so losing it costs a rail its input but leaves nothing unpaid-for. Blocked all the same —
    # the rails are reading an incomplete ledger — but never described as unreconciled spend.
    _broken_ledger(tmp_path, monkeypatch)

    record_questions("identity", 3)

    fault = usage.accounting_fault()
    assert fault is not None
    assert "UNRECONCILED" not in fault
    assert "No provider call is unaccounted for" in fault


def test_a_latched_fault_outlives_the_process_that_raised_it(tmp_path, monkeypatch):
    # The CLI is one process per invocation, so an in-memory latch alone would forget every fault
    # between commands. `reset_accounting_state` is exactly what a fresh process starts from.
    _broken_ledger(tmp_path, monkeypatch)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=10, completion_tokens=5)

    usage.reset_accounting_state()

    assert "UNRECONCILED" in (usage.accounting_fault() or "")


def test_repairing_the_path_does_not_by_itself_forgive_the_unrecorded_call(tmp_path, monkeypatch):
    # A writable path is not a reconciled ledger: the row whose write failed is still missing, so the
    # day total is still wrong. Clearing on repair alone would be "treat the unknown spend as zero"
    # with extra steps.
    ledger = _broken_ledger(tmp_path, monkeypatch)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200)

    ledger.rmdir()  # the operator fixes the path

    assert usage.check_ledger_writable() is None
    assert "UNRECONCILED" in (usage.accounting_block_reason() or "")


def test_reconcile_replays_the_held_row_instead_of_forgiving_it(tmp_path, monkeypatch):
    ledger = _broken_ledger(tmp_path, monkeypatch)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200)
    ledger.rmdir()

    note = usage.reconcile_accounting()

    assert "Reconciled 1 held ledger row(s)" in note
    assert usage.accounting_block_reason() is None
    assert not usage.ledger_fault_path(ledger).exists()
    # The point of replaying rather than clearing: the day's total is right again afterwards.
    assert usage_for_day()["openai"]["total"] == 1200


def test_a_failed_reconcile_neither_loses_the_held_row_nor_replays_it_twice(tmp_path, monkeypatch):
    # Running --reconcile before fixing the path is the obvious operator mistake, so the failed
    # attempt must be a no-op: the row stays held, and the reconcile that eventually succeeds counts
    # it exactly once. Losing it would forgive real spend; replaying it twice would invent spend.
    ledger = _broken_ledger(tmp_path, monkeypatch)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=100, completion_tokens=20)

    with pytest.raises(OSError):
        usage.reconcile_accounting()

    assert "UNRECONCILED" in (usage.accounting_fault() or "")
    assert usage.ledger_fault_path(ledger).exists()

    ledger.rmdir()
    usage.reconcile_accounting()

    assert usage.usage_for_day()["openai"] == {"prompt": 100, "completion": 20, "total": 120, "calls": 1}
    assert usage.accounting_block_reason() is None


def test_reconcile_says_so_when_a_fault_carries_no_replayable_row(tmp_path, monkeypatch):
    # The residual this design cannot repair: a fault raised when even the sidecar was unwritable,
    # whose process has since exited. We know a call went unrecorded but not what it cost — and the
    # one thing that must never happen is calling that zero.
    ledger = tmp_path / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    usage.ledger_fault_path(ledger).write_text(
        json.dumps({"ts": utc_date() + "T00:00:00+00:00", "kind": "accounting_fault", "billed": True}) + "\n",
        encoding="utf-8",
    )

    note = usage.reconcile_accounting()

    assert "stays unknown, not zero" in note
    assert usage.accounting_block_reason() is None


def test_a_fault_that_cannot_even_be_parked_still_blocks_this_process(tmp_path, monkeypatch):
    # Worst case: the ledger's whole directory is unusable, so the sidecar fails too. The in-process
    # latch is the only thing left — and it is enough, because the path is still unwritable, so the
    # pre-call probe blocks the NEXT process on its own.
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(occupied / "usage-ledger.jsonl"))

    record_usage("openai", "gpt-5.4-mini", prompt_tokens=10, completion_tokens=5)

    assert "UNRECONCILED" in (usage.accounting_fault() or "")
    usage.reset_accounting_state()  # a fresh process: the fault itself is gone...
    assert usage.accounting_fault() is None
    assert usage.accounting_block_reason() is not None  # ...but metered work is still refused


def test_record_usage_never_raises_on_io_failure(tmp_path):
    # Unchanged invariant: a ledger write happens mid-judgment, after the provider has answered, so
    # it must not be the thing that crashes the judgment. What changed is what happens next — the
    # loss is latched and blocks the following call instead of being written off as noise.
    unwritable = tmp_path / "dir-as-file"
    unwritable.write_text("occupied", encoding="utf-8")
    record_usage("openai", "m", prompt_tokens=1, completion_tokens=1, path=unwritable / "ledger.jsonl")
    assert usage.accounting_fault(path=unwritable / "ledger.jsonl") is not None


def test_the_call_gate_remembers_a_good_path_but_re_probes_a_bad_one(tmp_path, monkeypatch):
    # Memoizing a failure would leave an operator who fixes the path refused until they restart the
    # server — the one remedy a Candidate on the web cannot apply.
    ledger = _broken_ledger(tmp_path, monkeypatch)
    assert usage.accounting_gate() is not None

    ledger.rmdir()

    assert usage.accounting_gate() is None


def test_a_sidecar_we_cannot_read_blocks_instead_of_reading_as_no_faults(tmp_path, monkeypatch, caplog):
    # QA-04. The realistic shape: an older root container left the sidecar 0600 root:root, then the
    # ledger path itself was fixed. "Cannot read the parked rows" must never collapse into "nothing
    # was parked" — that is the same forgiveness as counting an unrecorded call as zero, one file at
    # a time, and it is the only place in this module where the money path fails OPEN.
    ledger = _broken_ledger(tmp_path, monkeypatch)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200)
    sidecar = usage.ledger_fault_path(ledger)
    ledger.rmdir()  # the operator fixes the ledger path...
    sidecar.chmod(0o000)  # ...but not the file holding the billed row
    usage.reset_accounting_state()  # a fresh process: only the sidecar remembers

    with caplog.at_level(logging.ERROR, logger="interview_coach.usage"):
        reason = usage.accounting_gate()

    assert reason is not None
    assert "UNRECONCILED" in reason
    assert str(sidecar) in reason
    # Logged the way an unreadable *ledger* already is (`_all_rows`): a fault nobody can see is a
    # fault nobody fixes.
    assert any(str(sidecar) in record.getMessage() for record in caplog.records)


def test_reconcile_never_clears_a_sidecar_it_could_not_read(tmp_path, monkeypatch):
    # Reconciliation ends by rewriting the sidecar to hold exactly what it could not replay — which,
    # for a file it never read, is nothing. Clearing it here would delete a billed row AND report
    # success, which is strictly worse than the fault it was called to fix.
    ledger = _broken_ledger(tmp_path, monkeypatch)
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200)
    sidecar = usage.ledger_fault_path(ledger)
    ledger.rmdir()
    sidecar.chmod(0o000)
    usage.reset_accounting_state()

    with pytest.raises(OSError):
        usage.reconcile_accounting()

    assert sidecar.exists()
    assert usage.accounting_block_reason() is not None

    sidecar.chmod(0o600)  # readable again: the held row was there all along

    assert "Reconciled 1 held ledger row(s)" in usage.reconcile_accounting()
    assert usage.usage_for_day()["openai"]["total"] == 1200


def test_a_torn_row_in_the_sidecar_is_held_as_unknown_spend_not_dropped(tmp_path, monkeypatch):
    # A process killed mid-append leaves a half-written last line. Skipping it on the decode error is
    # the same forgiveness one row at a time: the fault clears, the tokens never come back, and
    # nobody is told. It has to count as a fault carrying no replayable row instead.
    ledger = tmp_path / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    good = {
        "ts": utc_date() + "T00:00:00+00:00",
        "kind": "accounting_fault",
        "billed": True,
        "entry": {
            "ts": utc_date() + "T00:00:00+00:00",
            "provider": "openai",
            "model": "m",
            "prompt_tokens": 1000,
            "completion_tokens": 200,
        },
    }
    usage.ledger_fault_path(ledger).write_text(
        json.dumps(good) + "\n" + '{"ts": "2026-09-15T00:00:00+00:00", "kind": "accounting_fau',
        encoding="utf-8",
    )

    note = usage.reconcile_accounting()

    assert "Reconciled 1 held ledger row(s)" in note  # the intact row still replays
    assert "stays unknown, not zero" in note  # ...and the torn one is said out loud, not dropped


def test_a_sidecar_that_is_not_valid_utf8_does_not_crash_the_call_gate(tmp_path, monkeypatch):
    # `read_text` raises UnicodeDecodeError, which is a ValueError, so it escapes the OSError catch
    # entirely — and `chat_json` RETRIES ValueError. An accounting gate the caller retries is not a
    # gate, and the StructuredOutputError it finally becomes is indistinguishable from a bad model
    # reply. It has to block, like every other unreadable-sidecar shape.
    ledger = tmp_path / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    usage.ledger_fault_path(ledger).write_bytes(b'{"kind": "accounting_fault", "billed": true}\n\xff\xfe')

    reason = usage.accounting_gate()

    assert reason is not None
    assert "UNRECONCILED" in reason


def _held_in_memory(tmp_path):
    """Latch a billed fault the sidecar could not take, then make its directory usable again.

    The realistic shape behind QA-12: the parent was a file, so `_flush_faults` failed and the fault
    survives only in `_FAULTS`, unparked. Every later `accounting_fault()` — i.e. every metered call
    — retries the park, so two Sessions retry it at the same time.
    """
    occupied = tmp_path / "state"
    occupied.write_text("occupied", encoding="utf-8")
    ledger = occupied / "usage-ledger.jsonl"
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200, path=ledger)
    occupied.unlink()
    occupied.mkdir()
    return ledger


def _concurrent_flush(tmp_path, monkeypatch):
    """Two threads retry the park at once, with the sidecar append slowed to make the overlap real."""
    ledger = _held_in_memory(tmp_path)
    real_write_row = usage._write_row

    def slow_write_row(entry, target):
        time.sleep(0.05)
        real_write_row(entry, target)

    monkeypatch.setattr(usage, "_write_row", slow_write_row)
    start = threading.Barrier(2)

    def flush() -> None:
        start.wait()
        usage.accounting_fault(path=ledger)

    threads = [threading.Thread(target=flush) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    monkeypatch.setattr(usage, "_write_row", real_write_row)
    return ledger


def test_two_sessions_flushing_at_once_park_one_row_not_two(tmp_path, monkeypatch):
    # QA-12. Snapshot-then-write-then-mark in three separate holds of the lock let both threads see
    # the same unparked fault. A sidecar row duplicated here is a billed call the reconcile below
    # will charge twice — and the money ledger has no way back from that.
    ledger = _concurrent_flush(tmp_path, monkeypatch)

    rows = usage.ledger_fault_path(ledger).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1, rows


def test_a_fault_parked_twice_is_still_billed_once(tmp_path, monkeypatch):
    # The consequence, stated in the unit that matters. Even if a duplicate reaches the sidecar
    # anyway — two PROCESSES can do it, and no in-process lock can stop them — replay must fold the
    # call in once. Over-counting the day is as wrong as forgiving it, just in the other direction.
    ledger = _concurrent_flush(tmp_path, monkeypatch)

    usage.reconcile_accounting(path=ledger)

    assert usage_for_day(path=ledger)["openai"]["total"] == 1200
    assert usage.accounting_block_reason(path=ledger) is None


def test_reconciling_twice_does_not_bill_the_held_row_twice(tmp_path, monkeypatch):
    # QA-13. `--reconcile` replays every held row and only THEN rewrites the sidecar, so any path
    # that leaves those rows on disk — the rewrite failing, the process dying, the server appending
    # underneath the CLI — hands the operator a retry that invents the spend a second time. The
    # restore below is exactly that on-disk state, written by hand so the test names the state and
    # not the mechanism.
    ledger = tmp_path / "usage-ledger.jsonl"
    sidecar = usage.ledger_fault_path(ledger)
    occupied = tmp_path / "broken"
    occupied.write_text("occupied", encoding="utf-8")
    record_usage("openai", "gpt-5.4-mini", prompt_tokens=1000, completion_tokens=200, path=occupied / "l.jsonl")
    held = [dict(fault["record"], ledger=str(ledger)) for fault in usage._FAULTS]
    usage.reset_accounting_state()
    sidecar.write_text("".join(json.dumps(row) + "\n" for row in held), encoding="utf-8")
    still_held = sidecar.read_text(encoding="utf-8")

    first = usage.reconcile_accounting(path=ledger)
    sidecar.write_text(still_held, encoding="utf-8")  # the rewrite never landed; the operator retries
    second = usage.reconcile_accounting(path=ledger)

    assert "Reconciled 1 held ledger row(s)" in first
    assert usage_for_day(path=ledger)["openai"]["total"] == 1200
    assert "already in the ledger" in second
    assert usage.accounting_block_reason(path=ledger) is None


def test_a_held_row_written_before_the_fault_id_still_replays_exactly_once(tmp_path):
    # Backward compatibility, pinned: a sidecar row parked by an older build carries no id, so there
    # is nothing to dedupe on and it must behave exactly as it did — replayed once, then cleared.
    # Inventing a key for it from its contents would collapse two same-second calls into one and
    # forgive a real charge, which is the one direction this module may never err in.
    ledger = tmp_path / "usage-ledger.jsonl"
    entry = {
        "ts": utc_date() + "T00:00:00+00:00",
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "prompt_tokens": 7,
        "completion_tokens": 3,
    }
    usage.ledger_fault_path(ledger).write_text(
        json.dumps(
            {
                "ts": utc_date() + "T00:00:00+00:00",
                "kind": "accounting_fault",
                "row": "tokens",
                "billed": True,
                "ledger": str(ledger),
                "error": "IsADirectoryError: legacy",
                "entry": entry,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    note = usage.reconcile_accounting(path=ledger)

    assert "Reconciled 1 held ledger row(s)" in note
    assert usage_for_day(path=ledger)["openai"]["total"] == 10


# --- AUDIT §3.2 row 3: the question-cap check and the reservation are one atomic step -------------


def test_two_simultaneous_starts_cannot_both_pass_the_question_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "3")
    barrier = threading.Barrier(2)
    outcomes: list[str | None] = []

    def reserve() -> None:
        barrier.wait()
        outcomes.append(reserve_questions("id-1", questions=3))

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count(None) == 1, outcomes
    assert sum("COACH_DAILY_QUESTION_CAP" in (reason or "") for reason in outcomes) == 1
    assert questions_today("id-1") == 3


def _reserve_and_park(read_flag, release, outcome: str) -> None:
    """Child process: enter reserve_questions' check->append window and park inside it.

    The widening is test-only and lives entirely in the child, so production ships no sleep: the
    child swaps in its own `_rows_for_day`, which signals after the read and waits before returning.
    The parent then knows the child is mid-reservation rather than hoping it is.
    """
    real_rows_for_day = usage._rows_for_day

    def parked(day, path):
        rows = list(real_rows_for_day(day, path))
        read_flag.set()
        release.wait(10)
        return iter(rows)

    usage._rows_for_day = parked
    reason = reserve_questions("id-1", questions=10)
    Path(outcome).write_text(reason or "", encoding="utf-8")


def test_a_second_process_cannot_pass_the_cap_the_first_is_already_taking(tmp_path, monkeypatch):
    # QA-09. `_RESERVATION_LOCK` is an object inside one interpreter; the ledger is a file every
    # process that can write it shares — two `coach api` processes on one state volume, a CLI beside
    # the server. A cap enforced only within one interpreter is not a cap: measured, both processes
    # read the same pre-reservation count of 0 and both reserved 10 against a cap of 10, and the day
    # closed on `questions_today() == 20`.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "10")
    child_outcome = tmp_path / "child-outcome.txt"

    # Forked before this process starts a thread of its own (3.12 deprecates fork from a
    # multi-threaded process), and forked rather than spawned so the child inherits the environment
    # this test just set and pays no interpreter start-up.
    ctx = mp.get_context("fork")
    child_read, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_reserve_and_park, args=(child_read, release, str(child_outcome)))
    child.start()
    assert child_read.wait(10), "the child never reached its reservation"

    outcomes: list[str | None] = []

    def reserve() -> None:
        outcomes.append(reserve_questions("id-1", questions=10))

    thread = threading.Thread(target=reserve)
    thread.start()
    # Unlocked this returns instantly with None — the bug. Locked, it is parked in flock() until the
    # child releases, so the join times out and the release below is what lets either finish.
    thread.join(0.5)
    release.set()
    child.join(10)
    thread.join(10)

    assert child.exitcode == 0
    assert questions_today("id-1") == 10  # the cap holds across the process boundary
    assert child_outcome.read_text(encoding="utf-8") == ""  # the child won the race and reserved
    assert outcomes and "COACH_DAILY_QUESTION_CAP" in (outcomes[0] or "")  # this process was refused


def test_a_released_reservation_gives_the_cap_back_without_rewriting_a_row(tmp_path, monkeypatch):
    # QA-08's ledger half. The ledger is append-only, so a refund is a compensating ROW of its own
    # kind — the same shape `quota_retry` already uses to answer `quota_exhausted` — never a mutation
    # and never a negative count smuggled onto a reservation row, which a torn line would be
    # indistinguishable from.
    ledger = _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "10")

    assert reserve_questions("id-1", questions=10) is None
    assert questions_today("id-1") == 10
    assert question_cap_reason("id-1", questions=1) is not None  # the cap really is full

    record_questions_released("id-1", 7, session="s-1")

    assert questions_today("id-1") == 3
    assert question_cap_reason("id-1", questions=7) is None
    assert questions_today("id-2") == 0  # per identity, like the reservation it answers
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in rows] == ["questions", "questions_released"]
    assert rows[0]["questions"] == 10  # the reservation row is untouched
    # A fifth row kind in the same file, and it must be as invisible to the token readers as the four
    # before it — a refund read as spend would corrupt the budget rail it sits next to.
    assert usage_for_day() == {}
    assert sessions_for_day() == {}
    # A release with no reservation behind it is floored at 0, never banked against the next start.
    record_questions_released("id-2", 5)
    assert questions_today("id-2") == 0


def _held_row(fault_id: str, *, prompt: int, completion: int) -> dict:
    """One row shaped exactly as `_latch_fault` parks it, written straight into the sidecar."""
    return {
        "ts": "2026-09-15T00:00:00+00:00",
        "id": fault_id,
        "kind": "accounting_fault",
        "row": "tokens",
        "billed": True,
        "ledger": "unused",
        "error": "OSError: injected",
        "entry": {
            "ts": "2026-09-15T00:00:00+00:00",
            "kind": "tokens",
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        },
    }


def _reconcile_and_park(entered, release, outcome):
    """Child: stop inside the reconcile window, between the sidecar read and the sidecar rewrite.

    The widening is test-only and lives entirely in the child, so production ships no sleep: the
    child swaps in its own `_write_row`, which signals after the first replayed row lands and waits
    before writing the second. The parent then knows the child is mid-reconcile rather than hoping
    it is.
    """
    real_write_row = usage._write_row
    first = {"done": False}

    def parked(entry, target):
        real_write_row(entry, target)
        if not first["done"]:
            first["done"] = True
            entered.set()
            release.wait(10)

    usage._write_row = parked
    Path(outcome).write_text(usage.reconcile_accounting(), encoding="utf-8")


def test_a_second_process_cannot_reconcile_the_rows_this_one_is_already_replaying(tmp_path, monkeypatch):
    # #123. `reconcile_accounting` reads the held rows, appends them to the ledger, then rewrites the
    # sidecar to hold exactly what is left — a read-modify-write across two files with no lock at
    # all, while the same module already owns one for `reserve_questions`. Two overlapping reconciles
    # (a cron beside an operator, or a CLI beside the server) each read the sidecar before either
    # rewrites it, and `done = _replayed_fault_ids(target)` is a snapshot taken before the first
    # append — so both see an empty dedup set and both bill every held row. `usage_for_day` sums
    # every token row without deduplicating on `fault`, so that is a real double count of spend that
    # was charged once.
    ledger = tmp_path / "usage-ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    sidecar = usage.ledger_fault_path(ledger)
    sidecar.write_text(
        json.dumps(_held_row("fault-a", prompt=1000, completion=200))
        + "\n"
        + json.dumps(_held_row("fault-b", prompt=30, completion=7))
        + "\n",
        encoding="utf-8",
    )
    child_outcome = tmp_path / "child-outcome.txt"

    # Forked before this process starts a thread of its own (3.12 deprecates fork from a
    # multi-threaded process), and forked rather than spawned so the child inherits the environment
    # this test just set.
    ctx = mp.get_context("fork")
    child_entered, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_reconcile_and_park, args=(child_entered, release, str(child_outcome)))
    child.start()
    assert child_entered.wait(10), "the child never reached its replay loop"

    notes: list[str] = []

    def reconcile() -> None:
        notes.append(usage.reconcile_accounting())

    thread = threading.Thread(target=reconcile)
    thread.start()
    # Unlocked this returns instantly having replayed both rows a second time — the bug. Locked, it
    # is parked in flock() until the child releases, so the join times out.
    thread.join(0.5)
    assert thread.is_alive(), "the second reconcile was not held out of the window"
    release.set()
    child.join(10)
    thread.join(10)

    assert child.exitcode == 0
    assert "Reconciled 2 held ledger row(s)" in child_outcome.read_text(encoding="utf-8")
    # The whole point: each billed call is folded in exactly once, so the day's total is the truth.
    assert usage_for_day()["openai"] == {"prompt": 1030, "completion": 207, "total": 1237, "calls": 2}
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert sorted(row["fault"] for row in rows) == ["fault-a", "fault-b"]
    # The loser re-read the sidecar under the lock and found it empty, rather than replaying a
    # snapshot taken before the winner wrote.
    assert notes == ["No accounting fault to reconcile."]


def test_the_held_row_sidecar_is_never_published_by_truncating_it(tmp_path, monkeypatch):
    # The sidecar IS the held rows. `Path.write_text` truncates in place, so a volume that fills
    # between the truncate and the write leaves 0 bytes under the real name — and `_parked_faults`
    # reads 0 bytes as "nothing is parked", which is the most permissive answer there is drawn from
    # the least readable input. `atomic_write_text` stages a sibling and renames, so a failed publish
    # is a no-op. This is the narrow half of #123; the lock above is the headline.
    ledger = tmp_path / "usage-ledger.jsonl"
    ledger.mkdir()  # unwritable as a file: every replay fails, so every row stays held
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    sidecar = usage.ledger_fault_path(ledger)
    held = [_held_row("fault-a", prompt=10, completion=2), _held_row("fault-b", prompt=20, completion=4)]
    sidecar.write_text("".join(json.dumps(row) + "\n" for row in held), encoding="utf-8")

    real_write_text = Path.write_text

    def refuse_truncating_publish(self, *args, **kwargs):
        assert self != sidecar, "the sidecar was published by truncation, not by rename"
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse_truncating_publish)

    with pytest.raises(OSError):
        usage.reconcile_accounting()

    # Nothing was replayable, so nothing was dropped: both rows are still held and still refuse spend.
    still_held = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    assert sorted(row["id"] for row in still_held) == ["fault-a", "fault-b"]
    assert "UNRECONCILED" in (usage.accounting_fault() or "")
