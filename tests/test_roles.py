"""Per-role model routing (ADR 0010, R-18) and the per-model json_schema capability override.

The contract under test:
- zero-change rollout: with no ROLE_* overrides, every non-judge role IS the pre-0010 router
  object, and the judge resolves to the same provider/model/temperature — only pinned;
- the judge is never behind the failover router (ADR 0009a);
- ROLE_* env overrides build dedicated pinned clients without touching the other roles;
- ``supports_json_schema`` is per provider entry (per-model in effect), env-overridable.
"""

from __future__ import annotations

import json

import pytest

from interview_coach.config import ROLE_NAMES, Settings
from interview_coach.llm import (
    GroqClient,
    LLMClient,
    LLMConfigurationError,
    LLMRouter,
    OpenAIClient,
    RoleClients,
    build_role_clients,
    ensure_role_clients,
)
from interview_coach.microloop import ScriptedCandidate, run_micro_loop
from interview_coach.rubric import Rubric
from interview_coach.seeds import SeedQuestion


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        primary_provider="openai",
        openai_api_key="test",
        openai_model="gpt-5.4-mini",
        groq_api_key="test",
        groq_model="groq-model",
        **overrides,
    )


class _RecordingClient(LLMClient):
    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls = 0

    def chat(self, messages, *, response_format=None, disable_thinking=False) -> str:
        self.calls += 1
        return self.replies.pop(0) if self.replies else "{}"


def test_default_bundle_shares_router_and_pins_judge():
    roles = build_role_clients(_settings())

    # Non-judge roles share the literal pre-0010 router object — byte-identical behavior.
    assert isinstance(roles.interviewer, LLMRouter)
    assert roles.supervisor is roles.interviewer
    assert roles.diagnostic is roles.interviewer
    assert roles.planner is roles.interviewer
    # The judge is the same provider/model/temperature, but pinned: no failover wrapper.
    assert isinstance(roles.judge, OpenAIClient)
    assert not isinstance(roles.judge, LLMRouter)
    assert roles.judge.model_name == roles.interviewer.model_name == "gpt-5.4-mini"
    assert roles.judge._settings.temperature == _settings().temperature


def test_non_router_default_serves_every_role():
    # Demo mode and every fake-based test pass a bare client — single-client semantics survive.
    fake = _RecordingClient()
    roles = build_role_clients(_settings(), fake)
    for role in ROLE_NAMES:
        assert getattr(roles, role) is fake


def test_role_override_builds_pinned_client_and_leaves_the_rest():
    settings = _settings(
        role_interviewer_provider="groq",
        role_interviewer_model="llama-x",
        role_interviewer_temperature=0.7,
    )
    roles = build_role_clients(settings)

    assert isinstance(roles.interviewer, GroqClient)
    assert roles.interviewer.model_name == "llama-x"
    assert roles.interviewer._settings.temperature == 0.7
    assert isinstance(roles.supervisor, LLMRouter)  # untouched role keeps the router
    assert isinstance(roles.judge, OpenAIClient)


def test_judge_override_stays_pinned_never_routed():
    settings = _settings(role_judge_model="gpt-5.4-nano", role_judge_temperature=0.0)
    roles = build_role_clients(settings)

    assert isinstance(roles.judge, OpenAIClient)
    assert not isinstance(roles.judge, LLMRouter)
    assert roles.judge.model_name == "gpt-5.4-nano"
    assert roles.judge._settings.temperature == 0.0


def test_overridden_role_on_unconfigured_provider_fails_loudly():
    # mimo has no key/base/model in _settings(): routing a role onto it must die at build time,
    # not resolve to a silent misroute mid-Session.
    settings = _settings(role_planner_provider="mimo")
    with pytest.raises(LLMConfigurationError, match="planner"):
        build_role_clients(settings)


def test_unknown_role_provider_name_fails_loudly():
    settings = _settings(role_judge_provider="zenmux")
    with pytest.raises(ValueError, match="ROLE_JUDGE_PROVIDER"):
        build_role_clients(settings)


def test_role_env_vars_reach_the_bundle(monkeypatch):
    monkeypatch.setenv("PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("GROQ_MODEL", "groq-model")
    monkeypatch.setenv("ROLE_SUPERVISOR_PROVIDER", "groq")
    monkeypatch.setenv("ROLE_SUPERVISOR_TEMPERATURE", "0.1")

    roles = build_role_clients(Settings(_env_file=None))

    assert isinstance(roles.supervisor, GroqClient)
    assert roles.supervisor._settings.temperature == 0.1


def test_supports_json_schema_defaults_are_the_verified_ones():
    roles = build_role_clients(_settings(role_supervisor_provider="groq"))
    assert roles.judge.supports_json_schema is True  # OpenAI: live-probed 2026-07-11
    assert roles.supervisor.supports_json_schema is False  # Groq: not verified -> off


def test_supports_json_schema_env_override_is_per_provider_entry():
    settings = _settings(
        openai_supports_json_schema=False,
        groq_supports_json_schema=True,
        role_supervisor_provider="groq",
    )
    roles = build_role_clients(settings)
    assert roles.judge.supports_json_schema is False
    assert roles.supervisor.supports_json_schema is True


def test_ensure_role_clients_normalizes_all_three_shapes():
    assert ensure_role_clients(None) is None
    fake = _RecordingClient()
    bundle = ensure_role_clients(fake)
    assert isinstance(bundle, RoleClients)
    assert bundle.judge is fake
    assert ensure_role_clients(bundle) is bundle


# --- the micro-loop actually splits the roles -----------------------------------------------------

_RUBRIC = Rubric(weights={"correctness": 1.0})


def _evaluation(score: int, *, follow_up: bool) -> str:
    return json.dumps(
        {
            "dimensions": {
                "correctness": {"score": score, "evidence": "no evidence"},
                "english_delivery": {"score": 4, "evidence": "no evidence"},
            },
            "weighted_score": float(score),
            "confidence": 0.8,
            "follow_up_recommended": follow_up,
            "follow_up_rationale": "n/a",
        }
    )


def _tool_plan() -> str:
    # The non-native JSON emulation path parses a flat ConceptToolRequest, not the native
    # tool_calls envelope (that shape lives at the FakeOpenAI transport layer, a different seam).
    return json.dumps(
        {
            "query": "bias variance mechanism",
            "skill": "ml_fundamentals",
            "language": None,
            "reason": "The candidate needs to explain the mechanism.",
        }
    )


def _follow_up_reply() -> str:
    return json.dumps(
        {
            "question": "What mechanism connects the L2 penalty to lower variance?",
            "targets": "penalty-to-variance mechanism",
        }
    )


def test_micro_loop_routes_judge_and_interviewer_separately():
    judge = _RecordingClient([_evaluation(2, follow_up=True), _evaluation(4, follow_up=False)])
    interviewer = _RecordingClient([_tool_plan(), _follow_up_reply()])
    seed = SeedQuestion(
        skill="ml_fundamentals",
        question="Explain the bias-variance tradeoff.",
        rubric=_RUBRIC,
        answers=(
            "The model is overfitting because variance dominates here.",
            "The L2 penalty shrinks weights which reduces variance directly.",
        ),
    )

    result = run_micro_loop(
        judge,
        seed,
        ScriptedCandidate(seed.answers),
        max_turns=2,
        interviewer_client=interviewer,
    )

    # Every Evaluator call rode the judge client; every Interviewer call rode the interviewer one.
    assert judge.calls == 2
    assert interviewer.calls == 2
    assert result.turns[1].is_follow_up
    assert result.turns[1].question == "What mechanism connects the L2 penalty to lower variance?"


def test_micro_loop_single_client_still_serves_both_roles():
    single = _RecordingClient([_evaluation(4, follow_up=False)])
    seed = SeedQuestion(
        skill="ml_fundamentals",
        question="Explain the bias-variance tradeoff.",
        rubric=_RUBRIC,
        answers=("The model is overfitting because variance dominates here.",),
    )

    result = run_micro_loop(single, seed, ScriptedCandidate(seed.answers), max_turns=1)

    assert single.calls == 1
    assert result.turns[0].evaluation.weighted_score == 4.0
