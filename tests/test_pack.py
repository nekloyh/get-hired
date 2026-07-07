from __future__ import annotations

from pathlib import Path

import pytest

from interview_coach.bank import BankError, load_pack
from interview_coach.concepts import InMemoryConceptStore
from interview_coach.demo_llm import DemoLLMClient
from interview_coach.diagnostic import SKILLS, diagnose
from interview_coach.seeds import QUESTION_BANK, rotation_offset, seed_count, select_seed_question
from interview_coach.supervisor import (
    SessionStatus,
    build_session_graph,
    initial_session_state,
    session_config,
)

FPT_PACK = Path(__file__).resolve().parents[1] / "data" / "packs" / "fpt"


def _write_pack(tmp_path, *, questions: str, concepts: str | None = None, pack: str | None = None) -> Path:
    root = tmp_path / "pack"
    root.mkdir()
    (root / "questions.yaml").write_text(questions, encoding="utf-8")
    (root / "concepts.yaml").write_text(
        concepts
        if concepts is not None
        else "\n".join(
            f"- {{id: c_{s}, skill: {s}, title: T, content: some content text}}" for s in SKILLS
        ),
        encoding="utf-8",
    )
    (root / "pack.yaml").write_text(pack if pack is not None else "name: Test Pack", encoding="utf-8")
    return root


def _full_bank_yaml(difficulty_ml: int = 3) -> str:
    # A minimal valid pack: one question per canonical Skill, each referencing its own concept.
    blocks = []
    for skill in SKILLS:
        diff = difficulty_ml if skill == "ml_fundamentals" else 3
        blocks.append(
            f"{skill}:\n"
            f"  - question: A {skill} question?\n"
            f"    difficulty: {diff}\n"
            f"    rubric: {{weights: {{correctness: 1.0}}}}\n"
            f"    answers: [an answer]\n"
            f"    expected_concepts: [c_{skill}]\n"
        )
    return "\n".join(blocks)


# --- load + fail-loud ---------------------------------------------------------------------------


def test_fpt_pack_loads_and_covers_every_canonical_skill():
    pack = load_pack(FPT_PACK)
    assert set(pack.questions) == set(SKILLS)
    assert sum(len(qs) for qs in pack.questions.values()) >= 20
    assert pack.metadata["name"] == "FPT-style ML fresher pack"
    # every expected_concepts id resolves (loader would have raised otherwise)
    concept_ids = {c.id for c in pack.concepts}
    for questions in pack.questions.values():
        for q in questions:
            assert set(q.expected_concepts) <= concept_ids


def test_missing_directory_dies_loudly(tmp_path):
    with pytest.raises(BankError, match="does not exist"):
        load_pack(tmp_path / "nope")


def test_dangling_concept_reference_dies_loudly(tmp_path):
    bad = _full_bank_yaml().replace("expected_concepts: [c_ml_fundamentals]", "expected_concepts: [c_ghost]")
    root = _write_pack(tmp_path, questions=bad)
    with pytest.raises(BankError, match="unknown concept id"):
        load_pack(root)


def test_missing_skill_dies_loudly(tmp_path):
    # Drop vietnamese_nlp from the questions.
    partial = "\n".join(
        block for block in _full_bank_yaml().split("\n\n") if not block.startswith("vietnamese_nlp:")
    )
    root = _write_pack(tmp_path, questions=partial)
    with pytest.raises(BankError, match="no question for Skill"):
        load_pack(root)


def test_bad_difficulty_dies_loudly(tmp_path):
    root = _write_pack(tmp_path, questions=_full_bank_yaml(difficulty_ml=9))
    with pytest.raises(BankError, match="difficulty"):
        load_pack(root)


def test_pack_without_name_dies_loudly(tmp_path):
    root = _write_pack(tmp_path, questions=_full_bank_yaml(), pack="role: engineer")
    with pytest.raises(BankError, match="name"):
        load_pack(root)


# --- selection: difficulty + rotation -----------------------------------------------------------


def test_target_difficulty_drives_which_question_is_chosen():
    pack = load_pack(FPT_PACK)
    diffs = {q.difficulty for q in pack.questions["ml_fundamentals"]}
    assert {2, 4} <= diffs  # the FPT ml_fundamentals set spans easy and hard
    easy = select_seed_question("ml_fundamentals", target_difficulty=2, bank=pack.questions)
    hard = select_seed_question("ml_fundamentals", target_difficulty=5, bank=pack.questions)
    assert easy.difficulty <= 2
    assert hard.difficulty >= 4
    assert easy.question != hard.question


def test_rotation_offset_varies_the_sequence_across_sessions():
    # Two different Session ids rotate the built-in bank to different starting questions.
    span = seed_count("ml_fundamentals")
    offsets = {rotation_offset(f"session-{i}", span) for i in range(20)}
    assert len(offsets) > 1  # ids hash to different rotations
    # Across many Session ids the first question is not always the same one — repeat users see variety.
    picks = {
        select_seed_question("ml_fundamentals", rotation=rotation_offset(f"s{i}", span)).question
        for i in range(span * 3)
    }
    assert len(picks) > 1


# --- end-to-end: a Session runs entirely from the pack ------------------------------------------


def test_session_runs_entirely_from_the_pack(tmp_path):
    pack = load_pack(FPT_PACK)
    client = DemoLLMClient()
    graph = build_session_graph(
        client,
        concept_store=InMemoryConceptStore(pack.concepts),
        question_bank=pack.questions,
        now=lambda: 1.0,
    )
    diagnostic = diagnose(  # deterministic Topic Plan (no client) is fine for the offline drive
        _profile(),
        None,
    )
    state = initial_session_state("pack-session", diagnostic, max_questions=3, started_at=0.0)
    final = graph.invoke(state, session_config("pack-session"))

    assert final["status"] == SessionStatus.COMPLETE.value
    # every asked question came from the pack, not the built-in bank
    pack_prompts = {q.question for qs in pack.questions.values() for q in qs}
    builtin_prompts = {q.question for qs in QUESTION_BANK.values() for q in qs}
    asked = {turn["question"] for item in final["transcript"] for turn in item.get("turns", [])}
    assert asked <= pack_prompts
    assert asked.isdisjoint(builtin_prompts)


def test_coach_pack_lint_cli_exit_codes(tmp_path):
    from interview_coach.cli import main

    assert main(["pack", "lint", str(FPT_PACK)]) == 0
    bad = _write_pack(
        tmp_path,
        questions=_full_bank_yaml().replace("expected_concepts: [c_ml_fundamentals]", "expected_concepts: [c_ghost]"),
    )
    assert main(["pack", "lint", str(bad)]) == 1


def _profile():
    from interview_coach.diagnostic import CandidateProfile

    return CandidateProfile(target_role="machine learning engineer")
