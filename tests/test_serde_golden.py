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
