"""Tests for the YAML-backed question + concept banks and their fail-loud loader (issues 0013/0008)."""

from __future__ import annotations

import copy

import pytest

from interview_coach import bank
from interview_coach.bank import BankError, load_concepts, load_questions
from interview_coach.concepts import ConceptNote
from interview_coach.diagnostic import SKILLS
from interview_coach.rubric import DIMENSIONS
from interview_coach.seeds import SeedQuestion

# --- the real shipped banks --------------------------------------------------------------------


def test_real_banks_cover_every_skill():
    questions = load_questions()
    concepts = load_concepts()
    concept_skills = {note.skill for note in concepts}
    for skill in SKILLS:
        assert questions.get(skill), f"no question for Skill {skill!r}"
        assert skill in concept_skills, f"no concept note for Skill {skill!r}"


def test_real_questions_carry_schema_fields():
    # 0013: every question carries a weighted rubric, expected concepts, and follow-up seeds.
    for skill, items in load_questions().items():
        for q in items:
            assert isinstance(q, SeedQuestion)
            assert q.skill == skill
            assert len(q.answers) >= 1
            assert q.follow_up_seeds, f"{skill} question has no follow_up_seeds: {q.question!r}"
            assert q.rubric.active, "rubric must score at least one dimension"


def test_real_expected_concepts_all_resolve():
    concept_ids = {note.id for note in load_concepts()}
    for items in load_questions().values():
        for q in items:
            dangling = [cid for cid in q.expected_concepts if cid not in concept_ids]
            assert not dangling, f"dangling expected_concepts: {dangling}"


def test_some_questions_disable_a_dimension_with_weight_zero():
    # 0013: irrelevant rubric dimensions are weighted 0 (a concept question isn't scored on mlops).
    disabled = [
        q
        for items in load_questions().values()
        for q in items
        if any(q.rubric.weights.get(d, 0.0) == 0.0 for d in DIMENSIONS)
    ]
    assert disabled, "expected at least one question to disable a rubric dimension with weight 0"


def test_vietnamese_context_is_represented():
    # 0013/0008: a light set of Vietnamese-context items, tagged to the vietnamese_nlp Skill.
    assert len(load_questions()["vietnamese_nlp"]) >= 3
    vi_notes = [n for n in load_concepts() if n.language == "vi"]
    assert len(vi_notes) >= 3


# --- fail-loud validation ----------------------------------------------------------------------


def _valid_concepts() -> list[dict]:
    return [{"id": f"{s}_c", "skill": s, "title": "T", "content": "body"} for s in SKILLS]


def _valid_questions() -> dict:
    return {
        s: [
            {
                "question": f"Question about {s}?",
                "rubric": {"weights": {"correctness": 1.0}},
                "answers": ["first", "second"],
                "expected_concepts": [f"{s}_c"],
                "follow_up_seeds": ["probe deeper"],
            }
        ]
        for s in SKILLS
    }


def _patch_yaml(monkeypatch, *, concepts: object, questions: object) -> None:
    def fake_read(filename: str):
        return concepts if filename == "concepts.yaml" else questions

    monkeypatch.setattr(bank, "_read_yaml", fake_read)


def test_valid_patched_banks_load(monkeypatch):
    _patch_yaml(monkeypatch, concepts=_valid_concepts(), questions=_valid_questions())
    assert len(load_concepts()) == len(SKILLS)
    loaded = load_questions()
    assert set(loaded) == set(SKILLS)
    assert all(isinstance(n, ConceptNote) for n in load_concepts())


def test_concepts_must_be_a_list(monkeypatch):
    _patch_yaml(monkeypatch, concepts={"not": "a list"}, questions=_valid_questions())
    with pytest.raises(BankError, match="top-level list"):
        load_concepts()


def test_duplicate_concept_id_is_rejected(monkeypatch):
    concepts = _valid_concepts()
    concepts.append(copy.deepcopy(concepts[0]))  # same id twice
    _patch_yaml(monkeypatch, concepts=concepts, questions=_valid_questions())
    with pytest.raises(BankError, match="duplicate concept id"):
        load_concepts()


def test_concept_with_non_canonical_skill_is_rejected(monkeypatch):
    concepts = _valid_concepts()
    concepts[0]["skill"] = "astrology"
    _patch_yaml(monkeypatch, concepts=concepts, questions=_valid_questions())
    with pytest.raises(BankError, match="canonical Skill"):
        load_concepts()


def test_missing_skill_coverage_is_rejected(monkeypatch):
    concepts = [c for c in _valid_concepts() if c["skill"] != "mlops"]  # drop mlops coverage
    _patch_yaml(monkeypatch, concepts=concepts, questions=_valid_questions())
    with pytest.raises(BankError, match="no note for Skill"):
        load_concepts()


def test_question_with_unknown_rubric_dimension_is_rejected(monkeypatch):
    questions = _valid_questions()
    questions["mlops"][0]["rubric"]["weights"] = {"vibes": 1.0}
    _patch_yaml(monkeypatch, concepts=_valid_concepts(), questions=questions)
    with pytest.raises(BankError, match="invalid rubric"):
        load_questions()


def test_question_with_empty_answers_is_rejected(monkeypatch):
    questions = _valid_questions()
    questions["mlops"][0]["answers"] = []
    _patch_yaml(monkeypatch, concepts=_valid_concepts(), questions=questions)
    with pytest.raises(BankError, match="answers"):
        load_questions()


def test_dangling_expected_concept_is_rejected(monkeypatch):
    questions = _valid_questions()
    questions["mlops"][0]["expected_concepts"] = ["does_not_exist"]
    _patch_yaml(monkeypatch, concepts=_valid_concepts(), questions=questions)
    with pytest.raises(BankError, match="unknown concept id"):
        load_questions()


def test_question_under_non_canonical_skill_is_rejected(monkeypatch):
    questions = _valid_questions()
    questions["astrology"] = questions.pop("mlops")
    _patch_yaml(monkeypatch, concepts=_valid_concepts(), questions=questions)
    with pytest.raises(BankError, match="canonical Skill"):
        load_questions()
