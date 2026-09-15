"""The ADR 0009 judge gate is (provider, model, base_url) — not the provider alone (M0-13)."""

from __future__ import annotations

import pytest

from interview_coach.config import BENCH_VALIDATED_JUDGES, Settings


def _settings(**overrides) -> Settings:
    # Merged, not splatted after the defaults: several tests override `openai_model` itself, and
    # `Settings(openai_model=..., **{"openai_model": ...})` is a TypeError, not an override.
    fields: dict[str, object] = {
        "_env_file": None,
        "primary_provider": "openai",
        "openai_api_key": "test",
        "openai_model": "gpt-5.4-mini",
        "groq_api_key": "test",
        "groq_model": "groq-model",
    }
    fields.update(overrides)
    return Settings(**fields)


def test_the_allowlist_holds_only_triples_with_a_green_bench_artifact():
    # docs/audits/calibration-bench-2026-07-27.md: openai/gpt-5.4-mini, 35/35 median-of-k k=3, four
    # invocations, zero straddling cases. gpt-4o-mini (18-19/20) and groq llama-3.3-70b (18/20, VN
    # over-scoring delta 2.00) are benched and RED, so neither is here.
    assert BENCH_VALIDATED_JUDGES == frozenset({("openai", "gpt-5.4-mini", "https://api.openai.com/v1")})


def test_a_judge_model_with_no_bench_artifact_is_refused():
    # The measured hole: the provider stayed `openai`, so the old provider-shaped gate waved through
    # a model that has never been benched — and every Evaluation from then on fed the Beta states
    # and the Skill ledger looking exactly like a measured one.
    with pytest.raises(ValueError, match="no green `coach bench` artifact"):
        _settings(openai_model="totally-not-benched-9000").role_config("judge")


def test_a_benched_but_red_judge_model_is_refused():
    # gpt-4o-mini IS in docs/audits/ — at 18/20 and 19/20. Having an artifact is not having a GREEN
    # one; this is the case a "we benched it once" allowlist would wrongly admit.
    with pytest.raises(ValueError, match="no green `coach bench` artifact"):
        _settings(openai_model="gpt-4o-mini").role_config("judge")


def test_a_redirected_base_url_is_refused():
    # A model id is only half an identity: the same name behind a proxy or a compatible gateway is a
    # different model, and no bench report covers it.
    with pytest.raises(ValueError, match="no green `coach bench` artifact"):
        _settings(openai_base_url="http://proxy.internal/v1").role_config("judge")


def test_role_judge_model_is_gated_too():
    # ROLE_JUDGE_MODEL was applied AFTER the old guard ran, so it bypassed the gate structurally, not
    # by omission — the override literally did not exist yet when the check ran. ADR 0010 is explicit
    # that moving this knob IS a judge change.
    with pytest.raises(ValueError, match="no green `coach bench` artifact"):
        _settings(role_judge_model="gpt-5.4-nano").role_config("judge")


def test_the_validated_triple_is_still_accepted():
    # The shipped default (.env.example) must keep working — this change is a gate, not a migration.
    assert _settings().role_config("judge").model == "gpt-5.4-mini"


def test_an_unconfigured_provider_still_reports_itself_as_unconfigured():
    # An empty model means "not configured", not "unvalidated judge". Conflating them would replace
    # `_pinned_role_client`'s actionable message ("set its API key, base URL, and model") with a
    # bench lecture that names no remedy the operator can act on.
    settings = Settings(_env_file=None, primary_provider="openai", openai_api_key="test")
    assert settings.role_config("judge").model == ""
