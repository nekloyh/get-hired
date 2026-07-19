"""Free-tier hardening: the client-side daily token ledger and the noise-telemetry counters."""

from __future__ import annotations

import json

from interview_coach import telemetry
from interview_coach.usage import (
    DEFAULT_DAILY_TOKEN_BUDGET,
    daily_token_budget,
    record_usage,
    remaining_today,
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
    stale = {"ts": "2001-01-01T00:00:00+00:00", "provider": "openai", "model": "m",
             "prompt_tokens": 999, "completion_tokens": 999}
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
