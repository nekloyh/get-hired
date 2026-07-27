#!/usr/bin/env python
"""Regenerate the serde golden artifacts (R-20 / GH #75).

The DoD for the typed-serde refactor is "replay bench output byte-identical pre/post". That is
deliberately NOT re-run as `coach bench`: the judge bench is a stochastic measurement of a live
model (ADR 0009 — one green invocation is not evidence, ~207k tokens a run), so it can neither
prove nor disprove that a pure refactor changed a byte.

What CAN prove it is pinning the deterministic inputs and outputs the refactor actually touches:
the replay artifact writer, the Supervisor prompt the replay bench feeds its judge, the Markdown
export, the CLI summary, the UI rows, and the Study-Planner retrieval queries. All six are offline,
free, and exact.

    python scripts/dump_serde_goldens.py [outdir]     # default: tests/golden

`tests/test_serde_golden.py` regenerates each of these and byte-compares, so any drift in the
serialized shape fails the offline suite rather than being discovered in a checkpoint months later.
"""

from __future__ import annotations

import io
import re
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from interview_coach import cli, supervisor, ui  # noqa: E402
from interview_coach.demo_llm import DemoLLMClient  # noqa: E402
from interview_coach.exporter import render_session_markdown  # noqa: E402
from interview_coach.llm import LLMClient, Message, ResponseFormat  # noqa: E402
from interview_coach.replay import (  # noqa: E402
    Persona,
    dump_replay_artifact,
    load_replay_artifact,
    run_persona_session,
)
from interview_coach.skill import SkillState  # noqa: E402
from interview_coach.study_planner import _gap_query, _transcript_evidence  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
# A real, drifted, pre-R-26 checkpoint: no language_mode, no ledger_prior_mastery, an 8-key trace, a
# 6-key evaluation, and three transcript items covering resolved / safety_cap / failed — with
# `error` present on exactly the third. Every absent-key hazard is exercised by loading this file,
# which a synthetic fixture written today would quietly not reproduce.
DRIFTED_CHECKPOINT = Path(__file__).resolve().parent.parent / "data" / "replay" / "deep-learning-strong.json"


_PERSONA = Persona(
    name="alice",
    mastery={"ml_fundamentals": 0.9, "deep_learning": 0.8, "mlops": 0.15, "system_design": 0.5},
)


class _PersonaTextClient(LLMClient):
    """Echoes the persona's level word, so answers are a deterministic function of the persona."""

    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        disable_thinking: bool = False,
    ) -> str:
        text = " ".join(m["content"] for m in messages)
        match = re.search(r"ability on this topic \(\w+\) is (\w+)", text)
        return f"A {match.group(1)} answer." if match else "An answer."


def _persona_final_state() -> dict:
    persona = _PERSONA
    # `now` is frozen: started_at lands in the state and would otherwise make every run differ.
    return run_persona_session(
        DemoLLMClient(),
        persona,
        session_id="alice-traj",
        candidate_client=_PersonaTextClient(),
        max_questions=3,
        now=lambda: 1.0,
    )


def _skill_state(raw) -> SkillState:
    # Spelled out rather than via SkillState.from_dict so this script runs identically on the
    # pre-refactor tree (where that classmethod does not exist yet) and after it.
    return SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))


def _capture(fn, *args) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        fn(*args)
    return buffer.getvalue()


def dump(outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    final_state = _persona_final_state()
    drifted = load_replay_artifact(DRIFTED_CHECKPOINT).final_state
    written = []

    trajectory = outdir / "replay-trajectory.json"
    dump_replay_artifact(trajectory, _PERSONA, final_state)
    written.append(trajectory)

    # THIS is the replay bench: replay_decision -> decide_next_move -> _build_supervisor_messages.
    # Identical prompt bytes mean an identical decision, modulo the judge's own sampling.
    prompt = supervisor._build_supervisor_messages(drifted)[1]["content"]
    written.append(_write(outdir / "supervisor-prompt.txt", prompt))
    written.append(_write(outdir / "session-export.md", render_session_markdown(final_state)))
    written.append(_write(outdir / "session-summary.txt", _capture(cli._print_session_summary, final_state)))
    written.append(_write(outdir / "skill-state-rows.txt", "\n".join(ui.render_skill_state_rows(final_state))))

    planner_lines = [_transcript_evidence(drifted), ""]
    for skill, raw in sorted(drifted.get("skill_states", {}).items()):
        planner_lines.append(f"--- {skill} gap_query ---")
        planner_lines.append(_gap_query(drifted, skill, SkillState.from_dict(raw) if hasattr(SkillState, "from_dict")
                                        else SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]),
                                                        beta=float(raw["beta"])), "must_have"))
    written.append(_write(outdir / "study-plan-prompts.txt", "\n".join(planner_lines)))
    return written


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else GOLDEN_DIR
    for path in dump(target):
        print(f"wrote {path} ({path.stat().st_size} B)")
