from __future__ import annotations

import json

from interview_coach.diagnostic import CandidateProfile, diagnose
from interview_coach.rubric import DIMENSIONS
from interview_coach.skill import SkillState
from interview_coach.supervisor import (
    SessionStatus,
    build_session_graph,
    initial_session_state,
    session_config,
)


def _diagnostic():
    return diagnose(
        CandidateProfile(
            target_role="machine learning engineer",
            claimed_skills={"ml_fundamentals": 4, "mlops": 2},
            target_companies=("Viettel",),
        )
    )


def _eval(score: int) -> str:
    payload = {
        "dimensions": {
            dim: {"score": score, "evidence": "no evidence"}
            for dim in DIMENSIONS
        },
        "weighted_score": float(score),
        "confidence": 0.8,
        "follow_up_recommended": False,
        "follow_up_rationale": "The answer is fully revealed.",
    }
    if score <= 3:
        # A weak english_delivery score must carry >= 3 phrase-level fixes (issue 0024).
        payload["delivery_fixes"] = ["fix one", "fix two", "fix three"]
    return json.dumps(payload)


def _decision(
    action: str,
    reasoning: str,
    *,
    target_skill: str | None = None,
    target_plan_index: int | None = None,
) -> str:
    return json.dumps(
        {
            "action": action,
            "reasoning": reasoning,
            "target_skill": target_skill,
            "target_plan_index": target_plan_index,
        }
    )


def _mastery(final: dict, skill: str) -> float:
    raw = final["skill_states"][skill]
    return SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"])).mastery


def test_weak_candidate_gets_extra_probe_and_keeps_low_mastery(make_client):
    client, _ = make_client(
        [
            _eval(2),
            _decision("extra_question", "Weak mlops evidence needs one more probe."),
            _eval(2),
            '{"bad": 1}',
            '{"bad": 1}',
        ]
    )
    state = initial_session_state("weak-trajectory", _diagnostic(), max_questions=2, started_at=0)

    final = build_session_graph(client, now=lambda: 1).invoke(state, session_config("weak-trajectory"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert final["stop_reason"] == "max_questions"
    assert [item["skill"] for item in final["transcript"]] == ["mlops", "mlops"]
    assert final["supervisor_decisions"][0]["action"] == "extra_question"
    assert _mastery(final, "mlops") < 0.35


def test_strong_candidate_terminates_early_with_high_mastery(make_client):
    client, _ = make_client(
        [
            _eval(5),
            _decision("end_early", "The Candidate is consistently above the evidence bar."),
            '{"bad": 1}',
            '{"bad": 1}',
        ]
    )
    state = initial_session_state("strong-trajectory", _diagnostic(), max_questions=5, started_at=0)

    final = build_session_graph(client, now=lambda: 1).invoke(state, session_config("strong-trajectory"))

    assert final["status"] == SessionStatus.COMPLETE.value
    assert final["stop_reason"] == "supervisor_end_early"
    assert len(final["transcript"]) == 1
    assert final["transcript"][0]["skill"] == "mlops"
    assert final["supervisor_decisions"][0]["action"] == "end_early"
    assert _mastery(final, "mlops") > 0.65
