"""Free-tier hardening: the client-side daily token ledger and the noise-telemetry counters."""

from __future__ import annotations

import json
from datetime import UTC, datetime

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
    record_quota_exhausted,
    record_usage,
    remaining_today,
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


def test_record_usage_never_raises_on_io_failure(tmp_path):
    # A ledger line lost to IO is noise; a crashed live judgment is not.
    unwritable = tmp_path / "dir-as-file"
    unwritable.write_text("occupied", encoding="utf-8")
    record_usage("openai", "m", prompt_tokens=1, completion_tokens=1, path=unwritable / "ledger.jsonl")


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
    #   per question (max_turns=4): 2 seed-render + 4x6 evaluations + 10 one panel
    #                               + 3x6 follow-ups + 2 supervisor            = 56
    #   per Session (max_questions=5): 2 Diagnostic + 5x56 + 2 Study Plan       = 284
    assert (usage.EVALUATION_CALLS, usage.PANEL_CALLS, usage.FOLLOW_UP_CALLS) == (6, 10, 6)
    assert worst_case_question_calls(4) == 56
    assert worst_case_session_calls(5, 4) == 284
    assert worst_case_session_tokens(5, 4) == 284 * WORST_CASE_TOKENS_PER_CALL
    assert worst_case_session_tokens(5, 4) == 766_800


def test_the_ceiling_is_bracketed_by_what_the_ledger_measured():
    # Above: a ceiling a real Session can reach fires on compliant behaviour, so the per-call figure
    # must cover the single largest call ever recorded, not any mean — a runaway is precisely the
    # case where the expensive call is the one that repeats.
    assert WORST_CASE_TOKENS_PER_CALL >= LARGEST_MEASURED_CALL_TOKENS
    assert worst_case_session_tokens(5, 4) > 20 * HEAVIEST_MEASURED_SESSION_TOKENS
    # Below: a ceiling one Session cannot fit under three times over is not bounding anything, which
    # is the thing the issue asked for ("nothing bounds a single session").
    assert worst_case_session_tokens(5, 4) < DEFAULT_DAILY_TOKEN_BUDGET // 3


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


def test_session_budget_env_override(monkeypatch):
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "77")
    assert session_token_budget(max_questions=5, max_turns=4) == 77
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "not-a-number")
    assert session_token_budget(max_questions=5, max_turns=4) == worst_case_session_tokens(5, 4)


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
    # Another provider's spend is not this provider's problem.
    assert start_refusal_reason("groq", questions=2) is None


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
