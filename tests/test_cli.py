"""CLI dispatch wiring for ``diagnose`` (issue 0009 follow-up).

The LLM Diagnostic agent must be the *default* Topic Plan path whenever a provider is configured,
with the deterministic path as the offline fallback — not an opt-in flag. These tests pin that
wiring at the ``main()`` boundary without touching a real provider.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from interview_coach import cli
from interview_coach.diagnostic import DiagnosticResult, TopicPlanSource


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
