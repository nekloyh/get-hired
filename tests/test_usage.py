"""Free-tier hardening: the client-side daily token ledger and the noise-telemetry counters."""

from __future__ import annotations

import json

from interview_coach import telemetry
from interview_coach.usage import (
    DEFAULT_DAILY_QUESTION_CAP,
    DEFAULT_DAILY_TOKEN_BUDGET,
    DEFAULT_SESSION_TOKEN_BUDGET,
    HEAVIEST_MEASURED_SESSION_TOKENS,
    SESSION_SETUP_TOKENS,
    SESSION_TOKENS_PER_QUESTION,
    budget_stop_reason,
    daily_question_cap,
    daily_token_budget,
    estimated_session_tokens,
    question_cap_reason,
    questions_today,
    record_questions,
    record_usage,
    remaining_today,
    session_scope,
    session_spend,
    session_token_budget,
    sessions_for_day,
    start_refusal_reason,
    token_identity,
    usage_for_day,
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


# --- R-25: per-session budget + free-tier product caps -------------------------------------------


def test_session_budget_env_override(monkeypatch):
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "77")
    assert session_token_budget() == 77
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "not-a-number")
    assert session_token_budget() == DEFAULT_SESSION_TOKEN_BUDGET


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


def test_session_scope_attributes_ledger_rows(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=100, completion_tokens=10)
    record_usage("openai", "m", prompt_tokens=5, completion_tokens=1)  # a bench/forge one-off

    assert sessions_for_day() == {"sess-a": 110, "": 6}
    assert session_spend("sess-a") == 110
    assert session_spend("never-ran") == 0
    # Attribution must not disturb the per-provider view the daily rail reads.
    assert usage_for_day()["openai"]["total"] == 116


def test_session_scope_restores_the_previous_attribution(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    with session_scope("outer"):
        with session_scope("inner"):
            record_usage("openai", "m", prompt_tokens=1, completion_tokens=0)
        record_usage("openai", "m", prompt_tokens=2, completion_tokens=0)

    assert sessions_for_day() == {"inner": 1, "outer": 2}


def test_question_rows_are_invisible_to_the_token_reader(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    record_questions("id-1", 3)
    record_questions("id-1", 2)
    record_questions("id-2", 4)

    assert questions_today("id-1") == 5
    assert questions_today("id-2") == 4
    assert questions_today("nobody") == 0
    # The mixed-row design rests on this: a question row must never be read as token spend.
    assert usage_for_day() == {}
    assert sessions_for_day() == {}


def test_question_rows_from_another_day_do_not_count(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
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


def test_start_refusal_fires_only_when_the_day_cannot_fund_the_session(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(estimated_session_tokens(2) + 1))

    assert start_refusal_reason("openai", questions=2) is None
    record_usage("openai", "m", prompt_tokens=2, completion_tokens=0)
    reason = start_refusal_reason("openai", questions=2)
    assert reason is not None
    assert "00:00 UTC" in reason  # the remedy, not just the refusal
    # Another provider's spend is not this provider's problem.
    assert start_refusal_reason("groq", questions=2) is None


def test_question_cap_reason_names_the_env_var(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "5")

    assert question_cap_reason("id-1", questions=5) is None
    record_questions("id-1", 1)
    reason = question_cap_reason("id-1", questions=5)
    assert reason is not None
    assert "COACH_DAILY_QUESTION_CAP" in reason
    assert question_cap_reason("id-2", questions=5) is None  # per identity, not global


def test_budget_stop_reason_is_silent_while_comfortably_in_budget(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=1000, completion_tokens=100)

    assert budget_stop_reason("sess-a", "openai", questions_left=4) is None


def test_budget_stop_reason_names_the_runaway_rail(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "1000")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=900, completion_tokens=100)

    reason = budget_stop_reason("sess-a", "openai", questions_left=4)
    assert reason is not None
    assert "LLM_SESSION_TOKEN_BUDGET" in reason
    # Suspend-and-resume (ADR 0005), never a bare stop — and surface-neutral, because the web
    # surface has no `--resume` flag to offer.
    assert "resume this Session" in reason


def test_budget_stop_reason_fires_on_daily_exhaustion(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "2000")
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=1900, completion_tokens=100)

    # Within the per-session budget, but the day cannot fund even one more question.
    assert budget_stop_reason("sess-a", "openai", questions_left=1) is not None
    assert "00:00 UTC" in budget_stop_reason("sess-a", "openai", questions_left=1)
    # Nothing left to ask: the Session is about to finish anyway, so there is nothing to suspend.
    assert budget_stop_reason("sess-a", "openai", questions_left=0) is None


def test_exactly_enough_budget_for_the_rest_is_not_a_breach(tmp_path, monkeypatch):
    # Boundary: "enough" means enough. A Session is never suspended for a shortfall of zero.
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(ledger))
    spent, questions_left = 500, 2
    needed = estimated_session_tokens(questions_left, include_setup=False)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(spent + needed))
    with session_scope("sess-a"):
        record_usage("openai", "m", prompt_tokens=spent, completion_tokens=0)

    assert budget_stop_reason("sess-a", "openai", questions_left=questions_left) is None
    # One token less and it is a breach.
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(spent + needed - 1))
    assert budget_stop_reason("sess-a", "openai", questions_left=questions_left) is not None


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
