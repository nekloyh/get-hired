"""Seed questions that give the micro-loop (slice 0005) and Session real content to run on.

The question bank itself lives in ``data/questions.yaml`` (issue 0013) so it is hand-editable and
diff-friendly; this module only defines the :class:`SeedQuestion` shape and loads + exposes the bank
through :func:`select_seed_question` / :func:`seed_count`. ``answers[0]`` is the reply to the question
itself, and ``answers[1:]`` are the canned replies to successive Follow-ups (the fixture Candidate of
ADR/issue 0005): a strong opener resolves in one turn, a weak one invites a Follow-up after which the
scripted replies improve so the loop converges instead of running away.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .bank import load_questions
from .rubric import Rubric

QuestionBank = dict[str, tuple["SeedQuestion", ...]]

# Difficulty used when a question carries no explicit tag — mid-scale, so an untagged bank still loads
# and selection degrades to plain rotation rather than crashing.
DEFAULT_DIFFICULTY = 3


@dataclass(frozen=True)
class SeedQuestion:
    """One question plus the fixture Candidate's scripted transcript for it."""

    skill: str
    question: str
    rubric: Rubric
    answers: tuple[str, ...]  # answers[0] -> the question; answers[1:] -> successive follow-ups
    difficulty: int = DEFAULT_DIFFICULTY  # 1–5; lets target_difficulty actually drive selection (0025)
    expected_concepts: tuple[str, ...] = ()  # concept-note ids this question is expected to surface
    follow_up_seeds: tuple[str, ...] = ()  # hand-written probe starters for the Interviewer

    def __post_init__(self) -> None:
        if not self.answers:
            raise ValueError("a seed question needs at least one candidate answer")
        if not 1 <= self.difficulty <= 5:
            raise ValueError(f"difficulty must be on the 1–5 scale, got {self.difficulty}")


# The bank is loaded + validated from YAML at import time; a malformed bank fails loudly here (bank.py).
QUESTION_BANK: QuestionBank = load_questions()

# Back-compat alias: the ml_fundamentals seeds are the original slice-0005 set used directly in tests.
SEED_QUESTIONS: tuple[SeedQuestion, ...] = QUESTION_BANK["ml_fundamentals"]


def rotation_offset(session_id: str, span: int) -> int:
    """A stable per-Session rotation so a returning Candidate does not get the identical sequence (0025).

    Derived from the Session id with a process-stable hash (``hash()`` is salted per process, which
    would make rotation non-reproducible across resume). Requires no ledger, but a new sitting — a new
    Session id — rotates the bank to a fresh starting point.
    """
    if span <= 0:
        return 0
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % span


def select_seed_question(
    skill: str,
    question_number: int = 0,
    *,
    target_difficulty: int | None = None,
    rotation: int = 0,
    bank: QuestionBank | None = None,
) -> SeedQuestion:
    """Pick a fixture question for a Skill.

    Questions are ranked by closeness to ``target_difficulty`` (when given), then rotated by
    ``rotation`` so repeat Sessions vary; ``question_number`` (the Skill's attempt count) walks down
    that ranking so a repeat probe lands on a *different* prompt. Falls back to plain rotation when no
    target is given. ``bank`` overrides the built-in reference bank (a loaded pack, 0025).
    """
    questions = (bank if bank is not None else QUESTION_BANK).get(skill)
    if not questions:
        raise ValueError(f"no seed question available for Skill {skill!r}")
    n = len(questions)

    def rank(i: int) -> tuple[int, int]:
        rotated = (i + rotation) % n
        if target_difficulty is None:
            return (0, rotated)
        return (abs(questions[i].difficulty - target_difficulty), rotated)

    order = sorted(range(n), key=rank)
    return questions[order[question_number % n]]


def seed_count(skill: str, *, bank: QuestionBank | None = None) -> int:
    """How many distinct seed questions exist for a Skill — the Supervisor's deviation budget."""
    questions = (bank if bank is not None else QUESTION_BANK).get(skill)
    if not questions:
        raise ValueError(f"no seed question available for Skill {skill!r}")
    return len(questions)
