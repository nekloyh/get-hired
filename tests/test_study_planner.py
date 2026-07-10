from __future__ import annotations

import json

from interview_coach.exporter import export_session_markdown, render_session_markdown
from interview_coach.resources import InMemoryResourceStore, seed_resource_store
from interview_coach.study_planner import plan_study, rank_study_targets

_RESOURCE_FOR_SKILL = {
    "ml_fundamentals": "ml_fundamentals_cross_validation",
    "deep_learning": "deep_learning_resnet_d2l",
    "mlops": "mlops_google_rules",
    "system_design": "system_design_backpressure_rate_limiting",
    "vietnamese_nlp": "vietnamese_nlp_phobert",
}


def _skill_state(skill: str, mastery: float, strength: float = 4.0) -> dict[str, float | str]:
    return {
        "skill": skill,
        "alpha": mastery * strength,
        "beta": (1.0 - mastery) * strength,
    }


def _state() -> dict:
    return {
        "session_id": "plan-session",
        "status": "complete",
        "stop_reason": "max_questions",
        "question_count": 2,
        "topic_plan": [
            {"skill": "mlops", "target_difficulty": 4, "rationale": "Must-have production skill."},
            {"skill": "system_design", "target_difficulty": 3, "rationale": "Architecture breadth."},
        ],
        "skill_states": {
            # mlops is slightly less weak than system_design, but Role criticality should put it first.
            "mlops": _skill_state("mlops", 0.45),
            "system_design": _skill_state("system_design", 0.35),
        },
        "skill_metadata": {
            "mlops": {"role_criticality": "must_have", "evidence_bar": 4.0},
            "system_design": {"role_criticality": "peripheral", "evidence_bar": 2.0},
        },
        "transcript": [
            {
                "skill": "mlops",
                "plan_index": 0,
                "stop_reason": "resolved",
                "resolved_weighted_score": 2.0,
                "resolved_confidence": 0.7,
                "skill_state": _skill_state("mlops", 0.45),
                "turns": [
                    {
                        "question": "How would you monitor drift?",
                        "answer": "I would retrain sometimes.",
                        "is_follow_up": False,
                        "grounding_concept_id": None,
                        "grounding_concept_title": None,
                        "evaluation": {
                            "dimensions": {
                                "correctness": {"score": 2, "evidence": "retrain sometimes"},
                                "system_thinking": {"score": 2, "evidence": "retrain sometimes"},
                            },
                            "weighted_score": 2.0,
                            "confidence": 0.7,
                            "follow_up_recommended": False,
                            "follow_up_rationale": "No monitoring trigger or business-risk threshold.",
                        },
                        "trace": {},
                    }
                ],
            }
        ],
        "supervisor_decisions": [
            {
                "after_question": 2,
                "action": "end_early",
                "deviation": True,
                "llm_reasoning": "Hard cap reached.",
            }
        ],
    }


def _plan_json(
    *skills: str,
    bad_resource: bool = False,
    review_days: tuple[int, ...] = (),
    empty_days: tuple[int, ...] = (),
) -> str:
    resource_ids = [_RESOURCE_FOR_SKILL[skill] for skill in skills]
    first_resource = "invented_resource" if bad_resource else resource_ids[0]
    return json.dumps(
        {
            "readiness_estimate": 0.42,
            "readiness_rationale": "Role-critical production gaps remain.",
            "prioritized_topics": [
                {
                    "priority": i,
                    "skill": skill,
                    "title": f"Close {skill} gap",
                    "rationale": "The final Skill state is below the evidence bar.",
                    "target_mastery": "Answer with mechanisms, tradeoffs, and one concrete example.",
                    "resource_ids": [first_resource if i == 1 else _RESOURCE_FOR_SKILL[skill]],
                }
                for i, skill in enumerate(skills, start=1)
            ],
            "schedule": [
                {
                    "day": day,
                    "focus": f"Review day {day}" if day in review_days else f"Practice day {day}",
                    "outcome": (
                        "Consolidate prior practice and write a short retrospective."
                        if day in review_days
                        else "Produce a short answer and one follow-up answer."
                    ),
                    "resource_ids": (
                        []
                        if day in review_days or day in empty_days
                        else [resource_ids[(day - 1) % len(resource_ids)]]
                    ),
                }
                for day in range(1, 15)
            ],
            "milestones": [
                {
                    "week": 1,
                    "description": "Explain the top gap without notes.",
                    "evidence": "A recorded answer covers the missing mechanism.",
                },
                {
                    "week": 2,
                    "description": "Complete a timed mixed-topic mock.",
                    "evidence": "The answer references resources and tradeoffs.",
                },
            ],
        }
    )


def test_rank_study_targets_prioritizes_weak_role_critical_skills():
    targets = rank_study_targets(_state())

    assert [target.skill for target in targets] == ["mlops", "system_design"]


def test_plan_study_materializes_only_catalog_resource_urls(make_client):
    client, fake = make_client([_plan_json("mlops", "system_design")])
    store = seed_resource_store(InMemoryResourceStore())

    plan = plan_study(client, _state(), resource_store=store, topic_count=2)

    assert plan.prioritized_topics[0].skill == "mlops"
    assert plan.prioritized_topics[0].resources[0].id == "mlops_google_rules"
    assert plan.prioritized_topics[0].resources[0].url == "https://developers.google.com/machine-learning/guides/rules-of-ml"
    assert [call["skill"] for call in store.search_calls] == ["mlops", "system_design"]
    prompt = fake.chat.completions.calls[0]["messages"][-1]["content"]
    assert "RESOURCE CANDIDATES" in prompt
    assert "mlops_google_rules" in prompt
    assert "invented" not in plan.model_dump_json()


def test_plan_study_rejects_unknown_resource_id_and_retries(make_client):
    client, fake = make_client(
        [_plan_json("mlops", "system_design", bad_resource=True), _plan_json("mlops", "system_design")]
    )

    plan = plan_study(client, _state(), resource_store=seed_resource_store(InMemoryResourceStore()), topic_count=2)

    assert plan.prioritized_topics[0].resources[0].id == "mlops_google_rules"
    assert fake.call_count == 2


def test_plan_study_accepts_a_review_day_with_no_resources_without_a_retry(make_client):
    # A consolidation/review day legitimately cites no new resource. The schema now allows an empty
    # schedule resource list, so the planner must accept it on the FIRST attempt rather than burning a
    # retry, while every prioritized topic still carries at least one resource.
    client, fake = make_client([_plan_json("mlops", "system_design", review_days=(7, 14))])

    plan = plan_study(client, _state(), resource_store=seed_resource_store(InMemoryResourceStore()), topic_count=2)

    assert fake.call_count == 1  # empty schedule resource_ids accepted, no retry
    by_day = {item.day: item for item in plan.schedule}
    assert by_day[7].resources == []  # review day carries no resource
    assert by_day[1].resources  # a normal day still does
    assert all(topic.resources for topic in plan.prioritized_topics)  # topics still require resources


def test_plan_study_rejects_unmarked_empty_schedule_day_and_retries(make_client):
    client, fake = make_client(
        [_plan_json("mlops", "system_design", empty_days=(7,)), _plan_json("mlops", "system_design")]
    )

    plan = plan_study(client, _state(), resource_store=seed_resource_store(InMemoryResourceStore()), topic_count=2)

    assert fake.call_count == 2
    assert all(item.resources for item in plan.schedule)


def test_plan_study_rejects_all_empty_schedule_days_and_retries(make_client):
    all_days = tuple(range(1, 15))
    client, fake = make_client(
        [_plan_json("mlops", "system_design", review_days=all_days), _plan_json("mlops", "system_design")]
    )

    plan = plan_study(client, _state(), resource_store=seed_resource_store(InMemoryResourceStore()), topic_count=2)

    assert fake.call_count == 2
    assert all(item.resources for item in plan.schedule)


def test_session_export_markdown_includes_transcript_evaluations_and_plan(tmp_path, make_client):
    client, _ = make_client([_plan_json("mlops", "system_design")])
    state = _state()
    state["study_plan"] = plan_study(
        client,
        state,
        resource_store=seed_resource_store(InMemoryResourceStore()),
        topic_count=2,
    ).model_dump(mode="json")

    output = export_session_markdown(state, tmp_path / "session.md")
    text = output.read_text()

    assert "# Interview Session: plan-session" in text
    assert "I would retrain sometimes." in text
    assert "Weighted score: **2.00/5**" in text
    assert "https://developers.google.com/machine-learning/guides/rules-of-ml" in text


def test_export_surfaces_evidence_degraded_warning():
    # issue 0033: an entirely-unverifiable citation trail is flagged in the transcript, so the export
    # surfaces "scored, but citations unverifiable" instead of silently presenting a full-trust score.
    state = _state()
    state["transcript"][0]["turns"][0]["evaluation"]["evidence_degraded"] = True
    degraded = render_session_markdown(state)
    assert "Evidence degraded" in degraded

    state["transcript"][0]["turns"][0]["evaluation"]["evidence_degraded"] = False
    clean = render_session_markdown(state)
    assert "Evidence degraded" not in clean  # a normal judgment shows no warning
