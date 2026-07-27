"""Typed views over SessionState's nested shapes (R-20 / GH #75)."""

from __future__ import annotations

from dataclasses import fields

import pytest

from interview_coach.microloop import TurnTrace
from interview_coach.session_serde import (
    DecisionRecord,
    TraceRecord,
    TranscriptItem,
    TurnRecord,
    decision_records,
    skill_states_from_mapping,
    sorted_skill_states,
    transcript_items,
)
from interview_coach.skill import SkillState


def test_trace_record_mirrors_turn_trace():
    # TraceRecord is a hand-synced READ mirror of the write-side dataclass. A field added to one and
    # not the other is exactly the silent drop this refactor exists to prevent.
    assert {f.name for f in fields(TraceRecord)} == {f.name for f in fields(TurnTrace)}


def test_a_read_view_refuses_to_be_re_serialized():
    # The direction guard: round-tripping would materialize defaults for keys that were absent and
    # drop keys this module does not model, quietly rewriting a checkpoint on the way through.
    item = TranscriptItem.from_dict({"skill": "mlops"})

    with pytest.raises(TypeError, match="write-path API"):
        item.to_dict()


def test_a_resolved_item_has_no_error_key_at_all():
    # Present-and-null is a different wire shape from absent, and the browser reads this.
    written = TranscriptItem(skill="mlops", plan_index=1).to_dict()

    assert "error" not in written


def test_a_failed_item_carries_the_error_and_zero_evidence():
    written = TranscriptItem.failed("mlops", SkillState.neutral("mlops"), plan_index=2, error=RuntimeError("boom"))

    assert written["error"] == "RuntimeError: boom"
    assert written["evidence_weight"] == 0.0
    assert written["turns"] == []
    # A crash is not evidence of low mastery: the prior is kept unchanged.
    assert written["skill_state"] == {"skill": "mlops", "alpha": 1.0, "beta": 1.0}


def test_transcript_item_requires_a_skill():
    # Five existing call sites already subscript it; tolerating absence would have them render an
    # empty heading or count attempts under a None key.
    with pytest.raises(KeyError):
        TranscriptItem.from_dict({"plan_index": 0})


def test_absent_keys_read_as_their_documented_defaults():
    # A pre-0021 checkpoint has no evidence_weight and no trace; it must still load.
    item = TranscriptItem.from_dict({"skill": "mlops", "turns": [{"question": "q", "answer": "a"}]})

    assert item.evidence_weight == 0.0
    assert item.stop_reason is None
    assert item.error is None
    assert item.turns[0].trace.llm_calls is None
    assert item.turns[0].evaluation == {}


def test_unknown_keys_are_ignored_rather_than_crashing():
    # Forward compatibility: a checkpoint written by a newer version must still load in an older one.
    record = DecisionRecord.from_dict({"action": "advance_plan", "some_future_field": 1})

    assert record.action == "advance_plan"


def test_turn_evaluation_stays_the_raw_mapping():
    # Load-bearing: the exporter renders `dimensions` in insertion order and the Study Planner sorts
    # over it. Re-emitting a declared field list would reorder them.
    dimensions = {"depth": {"score": 2}, "correctness": {"score": 4}}
    turn = TurnRecord.from_dict({"evaluation": {"dimensions": dimensions}})

    assert list(turn.evaluation["dimensions"]) == ["depth", "correctness"]


def test_sorted_skill_states_sorts_by_the_dict_key():
    # The dict key is what labels rows and looks up skill_metadata; it is only incidentally equal to
    # raw["skill"], so sorting by the inner value would be a different (and wrong) order.
    state = {
        "skill_states": {
            "zzz": {"skill": "aaa", "alpha": 1.0, "beta": 1.0},
            "aaa": {"skill": "zzz", "alpha": 2.0, "beta": 1.0},
        }
    }

    assert [key for key, _ in sorted_skill_states(state)] == ["aaa", "zzz"]
    assert skill_states_from_mapping(state)["zzz"].skill == "aaa"


def test_empty_state_reads_as_empty_rather_than_raising():
    assert transcript_items({}) == ()
    assert decision_records({}) == ()
    assert skill_states_from_mapping({}) == {}
