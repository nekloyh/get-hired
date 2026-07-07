from __future__ import annotations

import json

import pytest

from interview_coach.diagnostic import (
    CandidateProfile,
    RoleCriticality,
    TopicPlanSource,
    diagnose,
    diagnose_or_degrade,
)
from interview_coach.evaluator import Evaluation
from interview_coach.skill import apply_evaluation


def _topic_plan_json() -> str:
    return json.dumps(
        {
            "topic_plan": [
                {
                    "skill": "mlops",
                    "target_difficulty": 4,
                    "rationale": "Must-have for the target role and should be probed early.",
                },
                {
                    "skill": "ml_fundamentals",
                    "target_difficulty": 3,
                    "rationale": "Core prerequisite for interpreting model trade-offs.",
                },
                {
                    "skill": "system_design",
                    "target_difficulty": 3,
                    "rationale": "Core for production architecture discussions.",
                },
                {
                    "skill": "deep_learning",
                    "target_difficulty": 3,
                    "rationale": "Related skill with weak prior evidence.",
                },
                {
                    "skill": "vietnamese_nlp",
                    "target_difficulty": 2,
                    "rationale": "Peripheral unless company context makes it more central.",
                },
            ]
        }
    )


def _evaluation(weighted_score: float) -> Evaluation:
    return Evaluation(
        dimensions={},
        weighted_score=weighted_score,
        confidence=0.9,
        follow_up_recommended=False,
        follow_up_rationale="n/a",
    )


def test_diagnostic_produces_topic_plan_entries():
    result = diagnose(
        CandidateProfile(
            target_role="machine learning engineer",
            claimed_skills={"ml_fundamentals": 4, "mlops": 2},
        )
    )

    assert result.topic_plan
    assert result.topic_plan_source is TopicPlanSource.DETERMINISTIC  # no client → offline fallback
    first = result.topic_plan[0]
    assert first.skill in result.priors
    assert 1 <= first.target_difficulty <= 5
    assert first.rationale


def test_seeded_priors_are_weak_and_direct_evidence_overrides_quickly():
    result = diagnose(
        CandidateProfile(
            target_role="research scientist",
            claimed_skills={"mlops": 5},  # peripheral here, so this is the strongest prior case.
        )
    )
    prior = result.priors["mlops"].state
    after_one = apply_evaluation(prior, _evaluation(1))
    after_two = apply_evaluation(after_one, _evaluation(1))

    assert prior.mastery > 0.5
    assert after_two.mastery < 0.5


def test_correlations_affect_only_initial_priors_not_later_evidence_updates():
    result = diagnose(CandidateProfile(target_role="research scientist", claimed_skills={"deep_learning": 5}))

    ml_fundamentals = result.priors["ml_fundamentals"].state
    before = (ml_fundamentals.alpha, ml_fundamentals.beta)
    apply_evaluation(result.priors["deep_learning"].state, _evaluation(5))
    after = (ml_fundamentals.alpha, ml_fundamentals.beta)

    assert ml_fundamentals.mastery > 0.5  # prior-only correlation from deep_learning.
    assert after == before  # no ongoing cross-credit after direct evidence.


def test_must_have_gets_weaker_prior_and_higher_evidence_bar_than_peripheral():
    mle = diagnose(
        CandidateProfile(target_role="machine learning engineer", claimed_skills={"mlops": 4})
    ).priors["mlops"]
    research = diagnose(
        CandidateProfile(target_role="research scientist", claimed_skills={"mlops": 4})
    ).priors["mlops"]

    assert mle.role_criticality is RoleCriticality.MUST_HAVE
    assert research.role_criticality is RoleCriticality.PERIPHERAL
    assert mle.prior_strength < research.prior_strength
    assert mle.evidence_bar > research.evidence_bar


def test_role_criticality_never_shifts_prior_mean():
    mle = diagnose(
        CandidateProfile(target_role="machine learning engineer", claimed_skills={"mlops": 4})
    ).priors["mlops"]
    research = diagnose(
        CandidateProfile(target_role="research scientist", claimed_skills={"mlops": 4})
    ).priors["mlops"]

    assert mle.state.mastery == pytest.approx(research.state.mastery)
    assert mle.prior_strength != research.prior_strength


def test_self_assessment_moves_mean_not_prior_confidence():
    low_claim = diagnose(
        CandidateProfile(target_role="research scientist", claimed_skills={"mlops": 1})
    ).priors["mlops"]
    high_claim = diagnose(
        CandidateProfile(target_role="research scientist", claimed_skills={"mlops": 5})
    ).priors["mlops"]

    assert low_claim.state.mastery < high_claim.state.mastery
    assert low_claim.state.confidence == pytest.approx(high_claim.state.confidence)


def test_diagnostic_agent_uses_single_shot_llm_for_topic_plan(make_client):
    client, fake = make_client([_topic_plan_json()])
    profile = CandidateProfile(
        target_role="machine learning engineer",
        claimed_skills={"mlops": 4},
    )

    result = diagnose(profile, client)

    assert result.topic_plan_source is TopicPlanSource.LLM  # client present → agent is the primary path
    assert [entry.skill for entry in result.topic_plan][0] == "mlops"
    assert result.priors["mlops"].role_criticality is RoleCriticality.MUST_HAVE
    assert fake.call_count == 1
    call = fake.chat.completions.calls[0]
    assert "SEEDED PRIORS AND ROLE CRITICALITY" in call["messages"][-1]["content"]
    assert "lookup_concept" not in call["messages"][0]["content"]


def test_diagnose_propagates_llm_failure_without_deterministic_fallback(make_client):
    # Deliberate non-fallback: a configured-LLM failure surfaces (codebase "don't silently degrade"
    # stance). Deterministic is the *offline* path, reached only when no client is supplied.
    client, _ = make_client([RuntimeError("provider down")])
    profile = CandidateProfile(target_role="machine learning engineer", claimed_skills={"mlops": 4})

    with pytest.raises(RuntimeError):
        diagnose(profile, client)


def test_diagnose_or_degrade_degrades_to_deterministic_on_provider_error(make_client):
    # Issue 0030: the Diagnostic runs before the graph, so the runtime backstop (not diagnose itself)
    # must catch a provider/transport error and degrade to the deterministic Topic Plan instead of
    # crashing the run. This is the exact failure that crashed `coach session` live.
    client, _ = make_client([RuntimeError("Groq 429: daily token limit reached")])
    profile = CandidateProfile(target_role="machine learning engineer", claimed_skills={"mlops": 4})

    result = diagnose_or_degrade(profile, client)

    assert result.topic_plan_source is TopicPlanSource.DETERMINISTIC
    assert result.topic_plan  # a usable plan, not a traceback
    assert result.priors["mlops"].role_criticality is RoleCriticality.MUST_HAVE


def test_diagnose_or_degrade_is_transparent_when_the_llm_succeeds(make_client):
    # The backstop only engages on failure: a healthy provider still yields the LLM Topic Plan.
    client, _ = make_client([_topic_plan_json()])
    profile = CandidateProfile(target_role="machine learning engineer", claimed_skills={"mlops": 4})

    result = diagnose_or_degrade(profile, client)

    assert result.topic_plan_source is TopicPlanSource.LLM
    assert [entry.skill for entry in result.topic_plan][0] == "mlops"


def test_diagnose_or_degrade_offline_matches_plain_diagnose():
    # With no client there is nothing to degrade from — identical to the deterministic diagnose path.
    profile = CandidateProfile(target_role="research scientist", claimed_skills={"mlops": 5})

    degraded = diagnose_or_degrade(profile, None)
    plain = diagnose(profile, None)

    assert degraded.topic_plan_source is TopicPlanSource.DETERMINISTIC
    assert [e.skill for e in degraded.topic_plan] == [e.skill for e in plain.topic_plan]
