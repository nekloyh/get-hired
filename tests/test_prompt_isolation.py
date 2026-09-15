"""ADR 0006: no prior-session memory may reach a probing or judging prompt.

The addendum (2026-07-19) splits the surfaces in two. *Presentation & planning* — the UI, exports
and the Study Planner's narrative — may consume session history ("last time you struggled with
backpressure"). *Probing & judging* — Supervisor, Interviewer, Evaluator (panel voices included),
and Diagnostic priors beyond the decayed Beta — may not: a remembered strong answer softening a
follow-up is the same masked-gap failure as a softened score. The ADR names this module as the
enforcement mechanism: "prompt-construction unit tests assert that no prior-session transcript text
enters the message lists built for the three probing agents. A violation is a red test, not a
code-review catch." Slice 0035 (GH #83) is the ADR's own named consumer and carries these tests in
its DoD.

The module is green today; it exists to go red the day coaching memory is plumbed into a probing
prompt. Four complementary mechanisms, because the builders take different kinds of input:

1. Poisoned state, absence assertion — for the builders that read ``SessionState``/profile+priors.
   Every slot a future coaching-memory feature would plausibly use carries ``_LEAK``.
2. Differential prompt equality — for the Supervisor, whose whole input is state: two states that
   differ ONLY in cross-session content must produce byte-identical prompts. Catches a leak through
   a key this module never thought to name.
3. End-to-end prompt capture — a whole Session driven from a poisoned state through per-role fake
   clients. Catches a leak plumbed anywhere between the state and the Evaluator/Interviewer, whose
   builders take scalars today and so cannot be poisoned directly. The planner's client is
   deliberately NOT asserted on: it is a planning surface the addendum permits history on.
4. A signature tripwire over every probing builder. Coaching memory cannot reach the Evaluator or
   the Interviewer without adding a parameter, so a new parameter is the thing to make loud.

Out of scope, on purpose: ``study_planner._build_study_planner_messages`` (planning surface),
``postmortem``'s elicitation/reconstruction prompts (a rejection debrief over the Candidate's own
in-session recollection, not coach-Session history), ``forge`` (offline question authoring) and
``replay.PersonaCandidate`` (a synthetic Candidate, not an agent).
"""

from __future__ import annotations

import copy
import inspect
import json
import re

import pytest

from interview_coach import diagnostic, evaluator, interviewer, supervisor
from interview_coach.diagnostic import (
    CandidateProfile,
    _build_diagnostic_messages,
    diagnose,
)
from interview_coach.llm import RoleClients
from interview_coach.supervisor import (
    SessionStatus,
    _build_supervisor_messages,
    build_session_graph,
    initial_session_state,
    session_config,
)

# One distinctive token, id-safe (ledger.SAFE_CANDIDATE_ID is [A-Za-z0-9_-]{1,64}) so it can also be
# planted in `candidate_id`, and improbable enough that a substring match cannot be a coincidence.
_LEAK = "pr10r-s3ss10n-9f3c1a"

# The ADR's own example of coaching memory, carrying the token.
_COACHING_NOTE = f"Last time you struggled with backpressure ({_LEAK}); here is the delta."

# Cross-session keys a coaching-memory feature would plausibly hang off SessionState. Named
# speculatively ON PURPOSE: mechanism 2 covers the names nobody guessed, this one makes the failure
# message say what leaked.
_FUTURE_MEMORY_KEYS = (
    "coaching_memory",
    "session_history",
    "prior_sessions",
    "prior_transcript",
    "last_session_summary",
)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        target_role="machine learning engineer",
        claimed_skills={"ml_fundamentals": 4, "mlops": 2},
        target_companies=("Viettel",),
    )


def _clean_state(session_id: str = "adr0006-session", **kwargs):
    return initial_session_state(session_id, diagnose(_profile()), started_at=0.0, **kwargs)


def _poison(state):
    """Return ``state`` with every plausible cross-session carrier holding ``_LEAK``.

    The *sanctioned* seam is untouched: ``ledger_prior_mastery`` stays numeric, because a decayed
    Beta prior is exactly what ADR 0006 permits to cross Sessions.
    """
    poisoned = copy.deepcopy(dict(state))
    poisoned["candidate_id"] = _LEAK
    poisoned["ledger_prior_mastery"] = {"mlops": 0.41, "ml_fundamentals": 0.62}
    for key in _FUTURE_MEMORY_KEYS:
        poisoned[key] = [_COACHING_NOTE]
    for meta in poisoned["skill_metadata"].values():
        meta["coaching_note"] = _COACHING_NOTE
    for row in poisoned["skill_states"].values():
        row["coaching_note"] = _COACHING_NOTE
    return poisoned


def _rendered(messages) -> str:
    return json.dumps(messages, ensure_ascii=False)


# --- 1. Supervisor -------------------------------------------------------------------------------


def test_the_supervisor_prompt_carries_no_prior_session_memory():
    body = _rendered(_build_supervisor_messages(_poison(_clean_state()), None))

    assert _LEAK not in body, "prior-session coaching memory reached the Supervisor prompt (ADR 0006)"


def test_cross_session_state_cannot_change_the_supervisor_prompt_at_all():
    # Key-name-agnostic: the two states share every current-Session field byte for byte and differ
    # only in cross-session carriers, so any difference in the rendered prompt IS the leak.
    clean = _clean_state()

    assert _build_supervisor_messages(_poison(clean), None) == _build_supervisor_messages(clean, None)


# --- 2. Diagnostic -------------------------------------------------------------------------------

_PRIOR_LINE = re.compile(
    r"^- (?P<skill>[a-z_]+): mastery=\d\.\d{3}, confidence=\d\.\d{3}, "
    r"criticality=(must_have|core|peripheral), evidence_bar=\d\.\d$"
)


def test_the_diagnostic_prior_block_is_numbers_only_for_a_returning_candidate():
    # ADR 0006 sanctions exactly one cross-session channel into the Diagnostic: the decayed Beta
    # mean, injected through `ledger_priors`. This pins the *shape* of what that channel can render,
    # so a coaching sentence appended to a prior line is a red test rather than a code-review catch.
    warm = diagnose(_profile(), None, ledger_priors={"mlops": 0.41, "ml_fundamentals": 0.62})

    body = _build_diagnostic_messages(_profile(), warm.priors)[1]["content"]
    block = body.split("SEEDED PRIORS AND ROLE CRITICALITY:\n", 1)[1].split("\n\n", 1)[0]

    assert [line for line in block.splitlines() if not _PRIOR_LINE.match(line)] == []


def test_the_diagnostic_prompt_ignores_memory_hung_off_the_candidate_profile():
    # A frozen dataclass cannot grow a field in this test, but it can be given one — which is the
    # point: if a future CandidateProfile carries coaching memory and the builder renders it, this
    # goes red without anyone having to remember to come back here.
    profile = _profile()
    object.__setattr__(profile, "coaching_memory", _COACHING_NOTE)
    warm = diagnose(profile, None, ledger_priors={"mlops": 0.41})

    assert _LEAK not in _rendered(_build_diagnostic_messages(profile, warm.priors))


# --- 3. Evaluator, panel voices and Interviewer, end to end --------------------------------------


def _evaluation_json(*, diverged: bool, follow_up: bool) -> str:
    # Every active dimension of a real bank rubric, plus the delivery dimension the en-mode loop
    # activates on an English answer. `diverged` makes the holistic weighted_score contradict the
    # mechanical mean, which is what trips the cross-check and escalates to the panel — the only way
    # the Skeptic/Advocate/verdict prompts exist at all to be captured.
    dimensions = {
        name: {"score": 5, "evidence": "no evidence"}
        for name in ("correctness", "depth", "communication", "system_thinking", "mlops_awareness")
    }
    dimensions["english_delivery"] = {"score": 4, "evidence": "no evidence"}
    return json.dumps(
        {
            "dimensions": dimensions,
            "weighted_score": 1.0 if diverged else 5.0,
            "confidence": 0.9,
            "follow_up_recommended": follow_up,
            "follow_up_rationale": "one more probe would separate recall from understanding",
        }
    )


def _panel_json(score: float) -> str:
    return json.dumps(
        {
            "recommended_score": score,
            "argument": "the answer names the mechanism but never applies it",
            "key_evidence": "the candidate's second sentence",
        }
    )


def _garbled_tool_reply() -> dict:
    # Every interviewer round-trip is a garbled tool name, so the follow-up degrades (ADR 0005)
    # AFTER both attempts have built and sent the Interviewer's prompt — which is all we capture.
    return {
        "tool_calls": [
            {
                "name": "lookup_concpet",
                "arguments": {"query": "backpressure", "skill": None, "language": None, "reason": "probe"},
            }
        ]
    }


def _decision_json(action: str) -> str:
    return json.dumps(
        {
            "action": action,
            "reasoning": "the evidence so far settles this Skill",
            "target_skill": None,
            "target_plan_index": None,
            "will_probe_skill": None,
        }
    )


def test_no_probing_agent_sees_prior_session_memory_across_a_whole_session(make_tool_client, make_client):
    judge, judge_fake = make_client(
        [
            _evaluation_json(diverged=True, follow_up=True),  # first pass: escalates to the panel
            _panel_json(2.0),  # skeptic
            _panel_json(4.0),  # advocate
            _evaluation_json(diverged=False, follow_up=True),  # panel verdict
        ]
    )
    asker, asker_fake = make_tool_client([_garbled_tool_reply()])  # clamped: every attempt is garbled
    sup, sup_fake = make_client([_decision_json("end_early")])
    # The Study Planner is a PLANNING surface: ADR 0006's addendum lets it see history, so this
    # module asserts nothing about its prompts. Scripting a plan it would reject keeps that
    # exclusion explicit and keeps the test off the resource catalogue's shape.
    planner, _ = make_client(["not a study plan"])
    roles = RoleClients(judge=judge, interviewer=asker, supervisor=sup, diagnostic=judge, planner=planner)

    state = _poison(_clean_state("adr0006-e2e", max_questions=2))
    final = build_session_graph(roles, now=lambda: 1).invoke(state, session_config("adr0006-e2e"))

    assert final["status"] == SessionStatus.COMPLETE.value
    # The run really did exercise every probing surface we claim to cover. A drifting count here
    # means the scripted replies stopped matching the bank's rubric, not that the invariant held.
    assert final["transcript"][0]["stop_reason"] != "failed"
    assert judge_fake.call_count == 4  # first pass + skeptic + advocate + verdict
    assert asker_fake.call_count == 2  # both Interviewer follow-up attempts
    assert sup_fake.call_count == 1

    for name, fake in (("judge", judge_fake), ("interviewer", asker_fake), ("supervisor", sup_fake)):
        sent = json.dumps([call["messages"] for call in fake.chat.completions.calls], ensure_ascii=False)
        assert _LEAK not in sent, f"prior-session coaching memory reached the {name} prompts (ADR 0006)"


# --- 4. The seam itself: what a probing builder is allowed to be handed -------------------------

# Every parameter of every probing/judging message builder, as of this commit. Each name here is
# either current-turn content (the question being asked, the answer just given, the judgment just
# made), a pure config knob (rubric, language_mode, role, bank), or the client that will carry the
# call. None of them can hold prior-session text.
#
# This is the tripwire for the builders whose inputs are scalars rather than state: a coaching-memory
# feature cannot reach the Evaluator or the Interviewer without adding a parameter, and adding one
# turns this red. If you are here because of that: decide whether the new input can carry
# prior-session transcript text. If it cannot, add it below with a one-line reason. If it can, ADR
# 0006 says it does not belong on a probing surface — route it to the UI, the export, or the Study
# Planner's narrative instead.
_PROBING_BUILDER_PARAMETERS = {
    "supervisor._build_supervisor_messages": {"state", "bank"},
    "diagnostic._build_diagnostic_messages": {"profile", "priors"},
    "evaluator._build_messages": {"question", "answer", "rubric", "language_mode"},
    "evaluator._panel_opinion": {"client", "question", "answer", "rubric", "first_pass", "role"},
    "evaluator._build_panel_verdict_messages": {
        "question",
        "answer",
        "rubric",
        "first_pass",
        "triggers",
        "skeptic",
        "advocate",
        "language_mode",
    },
    "interviewer._build_tool_messages": {"original_question", "answer", "evaluation", "skill"},
    "interviewer._build_follow_up_messages": {
        "original_question",
        "answer",
        "evaluation",
        "lookup",
        "language_mode",
    },
    "interviewer._build_native_user": {"original_question", "answer", "evaluation", "skill", "language_mode"},
    "interviewer.render_seed_question": {"client", "question", "language_mode"},
}

_MODULES = {
    "supervisor": supervisor,
    "diagnostic": diagnostic,
    "evaluator": evaluator,
    "interviewer": interviewer,
}


@pytest.mark.parametrize("dotted", sorted(_PROBING_BUILDER_PARAMETERS))
def test_no_probing_builder_has_grown_an_input_that_could_carry_memory(dotted):
    module, name = dotted.split(".")
    builder = getattr(_MODULES[module], name)

    assert set(inspect.signature(builder).parameters) == _PROBING_BUILDER_PARAMETERS[dotted]
