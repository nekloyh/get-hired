"""Tests for seed-question selection and exhaustion signalling (issue 0032 / GH #36).

``select_seed_question`` serves ``seed_count`` distinct prompts for a Skill across attempts
``0..n-1``. Asking for attempt ``n`` or beyond used to silently wrap (``order[question_number % n]``)
and re-serve an already-asked prompt, quietly defeating the rotation's duplicate-avoidance intent.
It now raises :class:`SeedQuestionsExhausted` instead, a loud, catchable signal so the caller can
skip/stop that Skill rather than repeat a question.
"""

from __future__ import annotations

import pytest

from interview_coach.seeds import (
    QUESTION_BANK,
    SeedQuestionsExhausted,
    rotation_offset,
    seed_count,
    select_seed_question,
)

ALL_SKILLS = tuple(QUESTION_BANK)


def test_attempts_below_seed_count_are_all_distinct():
    """Attempts 0..n-1 must each yield a different prompt for every Skill (the rotation's whole point)."""
    for skill in ALL_SKILLS:
        n = seed_count(skill)
        prompts = [select_seed_question(skill, i).question for i in range(n)]
        assert len(set(prompts)) == n, f"{skill} re-served a duplicate within its seed count: {prompts}"


def test_selecting_at_seed_count_raises_instead_of_wrapping():
    """The wraparound case: attempt == n used to return attempt 0's prompt; it must now signal exhaustion."""
    n = seed_count("ml_fundamentals")
    with pytest.raises(SeedQuestionsExhausted) as excinfo:
        select_seed_question("ml_fundamentals", n)
    err = excinfo.value
    assert err.skill == "ml_fundamentals"
    assert err.requested == n
    assert err.available == n


def test_selecting_past_seed_count_raises_for_every_skill():
    """No Skill silently wraps: the first attempt past its seed count raises for all of them."""
    for skill in ALL_SKILLS:
        n = seed_count(skill)
        with pytest.raises(SeedQuestionsExhausted):
            select_seed_question(skill, n)
        with pytest.raises(SeedQuestionsExhausted):
            select_seed_question(skill, n + 5)


def test_exhaustion_is_a_lookup_error():
    """Callers that catch ``LookupError`` (the concept-lookup convention) also catch this."""
    n = seed_count("mlops")
    with pytest.raises(LookupError):
        select_seed_question("mlops", n)


def test_exhaustion_message_names_the_skill_and_counts():
    n = seed_count("deep_learning")
    with pytest.raises(SeedQuestionsExhausted) as excinfo:
        select_seed_question("deep_learning", n + 1)
    message = str(excinfo.value)
    assert "deep_learning" in message
    assert str(n) in message


def test_target_difficulty_still_drives_selection():
    """Exhaustion guard must not disturb the difficulty-ranked ordering (0025)."""
    # ml_fundamentals spreads difficulties 1–5 (0013 breadth), so extreme targets land exactly.
    easy = select_seed_question("ml_fundamentals", 0, target_difficulty=1)
    hard = select_seed_question("ml_fundamentals", 0, target_difficulty=5)
    assert easy.difficulty == 1
    assert hard.difficulty == 5
    assert easy.question != hard.question


def test_rotation_stays_within_the_distinct_set():
    """A per-Session rotation varies the starting point but never escapes the n distinct prompts."""
    skill = "ml_fundamentals"
    n = seed_count(skill)
    span = n
    rotated = {
        select_seed_question(skill, 0, rotation=rotation_offset(f"session-{i}", span)).question
        for i in range(10)
    }
    all_prompts = {q.question for q in QUESTION_BANK[skill]}
    assert rotated <= all_prompts


def test_unknown_skill_still_raises_value_error():
    """A missing Skill is a caller error (unchanged), distinct from seed exhaustion."""
    with pytest.raises(ValueError):
        select_seed_question("not_a_real_skill", 0)


def test_seed_count_matches_bank_length():
    for skill in ALL_SKILLS:
        assert seed_count(skill) == len(QUESTION_BANK[skill])
