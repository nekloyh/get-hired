"""Byte-identity gate for the serialized Session shape (R-20 / GH #75).

The refactor's DoD is "replay bench output byte-identical pre/post". Re-running `coach bench` cannot
establish that: it measures a live, stochastic judge (ADR 0009 — one green invocation is not
evidence, ~207k tokens a run), so it would neither catch a serialization change nor exonerate one.

These goldens do establish it. They pin the six deterministic surfaces the refactor touches,
generated from the tree BEFORE any of it landed:

- `replay-trajectory.json` — the whole write path, via `dump_replay_artifact`.
- `supervisor-prompt.txt`  — *this is the replay bench*: `replay_decision` -> `decide_next_move` ->
  `_build_supervisor_messages`. Identical prompt bytes mean an identical decision, modulo sampling.
- `session-export.md`      — exporter over transcript items, decision records, skill states, traces
  and the Study Plan.
- `session-summary.txt`    — the CLI's strict-subscript read path.
- `skill-state-rows.txt`   — the UI's rounding.
- `study-plan-prompts.txt` — retrieval-query whitespace and dimension tie order.

Regenerate deliberately with `python scripts/dump_serde_goldens.py` — and only when a *behaviour*
change is intended, since that is exactly what these files exist to make loud.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from interview_coach.exporter import render_session_markdown

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GOLDEN_DIR = _REPO_ROOT / "tests" / "golden"


def _load_generator():
    """Import the generator script by path — `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "dump_serde_goldens", _REPO_ROOT / "scripts" / "dump_serde_goldens.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

GOLDEN_NAMES = (
    "replay-trajectory.json",
    "supervisor-prompt.txt",
    "session-export.md",
    "session-summary.txt",
    "skill-state-rows.txt",
    "study-plan-prompts.txt",
)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory) -> dict[str, str]:
    outdir = tmp_path_factory.mktemp("serde-goldens")
    return {path.name: path.read_text(encoding="utf-8") for path in _load_generator().dump(outdir)}


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_serialized_shape_is_byte_identical(name, regenerated):
    expected = (_GOLDEN_DIR / name).read_text(encoding="utf-8")

    assert regenerated[name] == expected, (
        f"{name} changed. If this refactor was meant to be behaviour-preserving, it was not: the "
        "serialized Session shape (or something rendering it) moved. Regenerate with "
        "`python scripts/dump_serde_goldens.py` only if the change is intended."
    )


def test_the_golden_set_is_complete():
    # A golden that stops being generated would otherwise pass silently forever.
    assert {p.name for p in _GOLDEN_DIR.iterdir()} == set(GOLDEN_NAMES)


# NEW-12: the export is the artifact a Candidate shows a recruiter, so its structure has to be the
# renderer's. `_md` escaped the pipe and nothing else, so a blank line plus a heading in the answer
# became a second, forged report section.
_FORGED_ANSWER = (
    "I am not sure.\n"
    "\n"
    "## Summary\n"
    "\n"
    "- Status: `complete`\n"
    "- Stop reason: `candidate_consistently_strong`\n"
    "- Questions: `12`\n"
)
# The judge quotes the Candidate verbatim, so the same payload arrives a second time inside the
# evidence cell — where a newline ends the table and everything after it is top-level Markdown.
_FORGED_EVIDENCE = "says `I am not sure`\n\n## Summary\n\n- Stop reason: `candidate_consistently_strong`"


def _forging_state(answer: str = _FORGED_ANSWER, evidence: str = "retrain sometimes") -> dict:
    return {
        "session_id": "forge-1",
        "status": "complete",
        "stop_reason": "max_questions",
        "question_count": 1,
        "transcript": [
            {
                "skill": "mlops",
                "plan_index": 0,
                "stop_reason": "resolved",
                "resolved_weighted_score": 2.0,
                "resolved_confidence": 0.7,
                "evidence_weight": 1.0,
                "turns": [
                    {
                        "question": "How would you monitor drift?",
                        "answer": answer,
                        "is_follow_up": False,
                        "evaluation": {
                            "dimensions": {"correctness": {"score": 2, "evidence": evidence}},
                            "weighted_score": 2.0,
                            "confidence": 0.7,
                            "follow_up_recommended": False,
                        },
                        "trace": {},
                    }
                ],
            }
        ],
    }


def test_a_candidate_answer_cannot_forge_report_sections():
    report = render_session_markdown(_forging_state())
    lines = report.splitlines()

    assert [line for line in lines if line.startswith("#")] == [
        "# Interview Session: forge-1",
        "## Summary",
        "## Final Skill States",
        "## Transcript",
        "### Question 1: `mlops`",
        "#### Turn 1: Question",
        "## Study Plan",
    ], "the Candidate's answer supplied its own headings: the report's structure has to come from the renderer"
    assert [line for line in lines if line.startswith("- Stop reason:")] == [
        "- Stop reason: `max_questions`"
    ], "a second, forged Summary bullet claims a stop reason the Session never reached"
    # Quoted, never censored: the answer is still in the record verbatim (ADR 0005).
    assert "candidate_consistently_strong" in report


def test_the_judges_quote_of_the_answer_cannot_break_the_evidence_table():
    report = render_session_markdown(_forging_state(answer="fine", evidence=_FORGED_EVIDENCE))
    lines = report.splitlines()

    assert [line for line in lines if line.startswith("- Stop reason:")] == [
        "- Stop reason: `max_questions`"
    ], "a newline in `evidence` ended the table, so the judge's quote of the answer became report structure"
    assert [line for line in lines if line.startswith("| correctness")] == [
        "| correctness | 2 | says `I am not sure`  ## Summary  - Stop reason: `candidate_consistently_strong` |"
    ], "the evidence cell must stay one row of the Dimension table"
    assert "candidate_consistently_strong" in report
