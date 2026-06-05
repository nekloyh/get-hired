"""Seed questions that give the micro-loop (slice 0005) and Session real content to run on.

The question bank itself lives in ``data/questions.yaml`` (issue 0013) so it is hand-editable and
diff-friendly; this module only defines the :class:`SeedQuestion` shape and loads + exposes the bank
through :func:`select_seed_question` / :func:`seed_count`. ``answers[0]`` is the reply to the question
itself, and ``answers[1:]`` are the canned replies to successive Follow-ups (the fixture Candidate of
ADR/issue 0005): a strong opener resolves in one turn, a weak one invites a Follow-up after which the
scripted replies improve so the loop converges instead of running away.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bank import load_questions
from .rubric import Rubric


@dataclass(frozen=True)
class SeedQuestion:
    """One question plus the fixture Candidate's scripted transcript for it."""

    skill: str
    question: str
    rubric: Rubric
    answers: tuple[str, ...]  # answers[0] -> the question; answers[1:] -> successive follow-ups
    expected_concepts: tuple[str, ...] = ()  # concept-note ids this question is expected to surface
    follow_up_seeds: tuple[str, ...] = ()  # hand-written probe starters for the Interviewer

    def __post_init__(self) -> None:
        if not self.answers:
            raise ValueError("a seed question needs at least one candidate answer")


# The bank is loaded + validated from YAML at import time; a malformed bank fails loudly here (bank.py).
QUESTION_BANK: dict[str, tuple[SeedQuestion, ...]] = load_questions()

# Back-compat alias: the ml_fundamentals seeds are the original slice-0005 set used directly in tests.
SEED_QUESTIONS: tuple[SeedQuestion, ...] = QUESTION_BANK["ml_fundamentals"]


def select_seed_question(skill: str, question_number: int = 0) -> SeedQuestion:
    """Pick a fixture question for a Skill, rotating when the Supervisor probes the same Skill again.

    The Supervisor's seed gate keeps ``question_number`` below ``seed_count(skill)`` for deviations,
    so the modulo never re-asks an already-used seed in practice; it stays as a final safety wrap.
    """
    questions = QUESTION_BANK.get(skill)
    if not questions:
        raise ValueError(f"no seed question available for Skill {skill!r}")
    return questions[question_number % len(questions)]


def seed_count(skill: str) -> int:
    """How many distinct seed questions exist for a Skill — the Supervisor's deviation budget."""
    questions = QUESTION_BANK.get(skill)
    if not questions:
        raise ValueError(f"no seed question available for Skill {skill!r}")
    return len(questions)
