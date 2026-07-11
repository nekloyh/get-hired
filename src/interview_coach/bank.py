"""Load the question + concept banks from YAML data files (issues 0013 / 0008).

The banks live in ``data/questions.yaml`` and ``data/concepts.yaml`` so they are hand-editable and
diff-friendly, then are validated into the existing frozen dataclasses (:class:`SeedQuestion`,
:class:`ConceptNote`) on load. Validation is deliberately loud: a malformed or internally inconsistent
bank should fail at import time, not silently ship a broken Session (the same fail-loud principle as
ADR 0003). Every Skill must carry at least one concept note and one question, and every question's
``expected_concepts`` must reference a concept note that actually exists.

To avoid an import cycle (``concepts``/``seeds`` call these loaders at module load, and the loaders
need the dataclasses those modules define), all of the model imports below are deferred into the
functions; this module imports nothing from the package at top level.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .concepts import ConceptNote
    from .seeds import SeedQuestion

_DATA_PACKAGE = "interview_coach"
_DATA_DIR = "data"

# A YAML reader: filename -> parsed data. The built-in bank reads packaged resources; a pack reads a
# filesystem directory. The loaders below are written against this so the validation is shared (0008).
YamlReader = Callable[[str], Any]


class BankError(ValueError):
    """A question/concept bank YAML file is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Pack:
    """A validated external content pack: questions + concept notes + metadata (ADR 0008)."""

    concepts: tuple[ConceptNote, ...]
    questions: dict[str, tuple[SeedQuestion, ...]]
    metadata: dict[str, Any]


def _read_yaml(filename: str) -> Any:
    text = resources.files(_DATA_PACKAGE).joinpath(_DATA_DIR, filename).read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as err:  # pragma: no cover - exercised via malformed-file tests
        raise BankError(f"{filename} is not valid YAML: {err}") from err


def _dir_reader(pack_dir: Path) -> YamlReader:
    def read(filename: str) -> Any:
        path = pack_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as err:
            raise BankError(f"pack file {path} is unreadable: {err}") from err
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as err:
            raise BankError(f"{path} is not valid YAML: {err}") from err

    return read


def _require_str(value: Any, *, where: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BankError(f"{where}: {field!r} must be a non-empty string, got {value!r}")
    return value


def _str_tuple(value: Any, *, where: str, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise BankError(f"{where}: {field!r} must be a list of non-empty strings, got {value!r}")
    return tuple(value)


def load_concepts() -> tuple[ConceptNote, ...]:
    """Parse the built-in ``data/concepts.yaml`` into validated :class:`ConceptNote` objects."""
    return _load_concepts(_read_yaml)


def _load_concepts(read: YamlReader) -> tuple[ConceptNote, ...]:
    from .concepts import ConceptNote
    from .diagnostic import SKILLS

    data = read("concepts.yaml")
    if not isinstance(data, list):
        raise BankError("concepts.yaml must be a top-level list of concept notes")

    notes: list[ConceptNote] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(data):
        where = f"concepts.yaml[{i}]"
        if not isinstance(raw, dict):
            raise BankError(f"{where}: each concept note must be a mapping, got {raw!r}")
        note_id = _require_str(raw.get("id"), where=where, field="id")
        if note_id in seen_ids:
            raise BankError(f"{where}: duplicate concept id {note_id!r}")
        seen_ids.add(note_id)
        skill = _require_str(raw.get("skill"), where=where, field="skill")
        if skill not in SKILLS:
            raise BankError(f"{where}: skill {skill!r} is not a canonical Skill {SKILLS}")
        notes.append(
            ConceptNote(
                id=note_id,
                skill=skill,
                title=_require_str(raw.get("title"), where=where, field="title"),
                content=_require_str(raw.get("content"), where=where, field="content"),
                language=raw.get("language", "en") or "en",
                tags=_str_tuple(raw.get("tags"), where=where, field="tags"),
            )
        )

    covered = {note.skill for note in notes}
    missing = [skill for skill in SKILLS if skill not in covered]
    if missing:
        # The Interviewer always filters lookup_concept by the current Skill, so a Skill with no note
        # would make every Follow-up on it degrade. Coverage is a hard requirement (issue 0008).
        raise BankError(f"concepts.yaml has no note for Skill(s): {missing}")
    return tuple(notes)


def load_questions() -> dict[str, tuple[SeedQuestion, ...]]:
    """Parse the built-in ``data/questions.yaml`` into validated :class:`SeedQuestion` objects."""
    return _load_questions(_read_yaml, {note.id for note in load_concepts()})


def _load_questions(read: YamlReader, concept_ids: set[str]) -> dict[str, tuple[SeedQuestion, ...]]:
    from .diagnostic import SKILLS
    from .rubric import Rubric
    from .seeds import DEFAULT_DIFFICULTY, SeedQuestion

    data = read("questions.yaml")
    if not isinstance(data, dict):
        raise BankError("questions.yaml must be a top-level mapping of Skill -> list of questions")

    bank: dict[str, tuple[SeedQuestion, ...]] = {}
    seen_questions: set[str] = set()
    for skill, items in data.items():
        if skill not in SKILLS:
            raise BankError(f"questions.yaml: {skill!r} is not a canonical Skill {SKILLS}")
        if not isinstance(items, list) or not items:
            raise BankError(f"questions.yaml[{skill}]: must be a non-empty list of questions")
        questions: list[SeedQuestion] = []
        for i, raw in enumerate(items):
            where = f"questions.yaml[{skill}][{i}]"
            if not isinstance(raw, dict):
                raise BankError(f"{where}: each question must be a mapping, got {raw!r}")
            prompt = _require_str(raw.get("question"), where=where, field="question")
            if prompt in seen_questions:
                raise BankError(f"{where}: duplicate question prompt {prompt!r}")
            seen_questions.add(prompt)

            weights = raw.get("rubric", {}).get("weights") if isinstance(raw.get("rubric"), dict) else None
            if not isinstance(weights, dict):
                raise BankError(f"{where}: 'rubric.weights' must be a mapping of dimension -> weight")
            if "english_delivery" in weights:
                # Issue 0024 / ADR 0007: delivery is Session state, not content. The micro-loop
                # activates english_delivery per answer from language_mode; a pack that authored it
                # would pin delivery scoring regardless of the Session's language.
                raise BankError(
                    f"{where}: 'english_delivery' must not be authored in a pack — it is "
                    "activated per answer by the Session's language_mode"
                )
            try:
                rubric = Rubric(weights={k: float(v) for k, v in weights.items()})
            except (ValueError, TypeError) as err:
                raise BankError(f"{where}: invalid rubric: {err}") from err

            answers = raw.get("answers")
            if (
                not isinstance(answers, list)
                or not answers
                or not all(isinstance(a, str) and a.strip() for a in answers)
            ):
                raise BankError(f"{where}: 'answers' must be a non-empty list of non-empty strings")

            expected_concepts = _str_tuple(raw.get("expected_concepts"), where=where, field="expected_concepts")
            dangling = [cid for cid in expected_concepts if cid not in concept_ids]
            if dangling:
                raise BankError(f"{where}: expected_concepts reference unknown concept id(s): {dangling}")

            difficulty = raw.get("difficulty", DEFAULT_DIFFICULTY)
            if isinstance(difficulty, bool) or not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
                raise BankError(f"{where}: 'difficulty' must be an integer on the 1–5 scale, got {difficulty!r}")

            try:
                questions.append(
                    SeedQuestion(
                        skill=skill,
                        question=prompt,
                        rubric=rubric,
                        answers=tuple(answers),
                        difficulty=difficulty,
                        expected_concepts=expected_concepts,
                        follow_up_seeds=_str_tuple(
                            raw.get("follow_up_seeds"), where=where, field="follow_up_seeds"
                        ),
                    )
                )
            except ValueError as err:
                raise BankError(f"{where}: {err}") from err
        bank[skill] = tuple(questions)

    missing = [skill for skill in SKILLS if skill not in bank]
    if missing:
        raise BankError(f"questions.yaml has no question for Skill(s): {missing}")
    return bank


def load_pack(pack_dir: str | Path) -> Pack:
    """Load + validate an external content pack directory (ADR 0008).

    A pack is a directory holding ``questions.yaml`` + ``concepts.yaml`` (same schema and fail-loud
    cross-referential validation as the built-in bank) plus a ``pack.yaml`` metadata file. Raises
    :class:`BankError` with a named violation on anything malformed — the contract dies at lint time,
    never mid-interview.
    """
    root = Path(pack_dir)
    if not root.is_dir():
        raise BankError(f"pack directory {root} does not exist or is not a directory")
    read = _dir_reader(root)
    concepts = _load_concepts(read)
    questions = _load_questions(read, {note.id for note in concepts})
    metadata = _load_pack_metadata(root)
    return Pack(concepts=concepts, questions=questions, metadata=metadata)


def _load_pack_metadata(pack_dir: Path) -> dict[str, Any]:
    data = _dir_reader(pack_dir)("pack.yaml")
    if not isinstance(data, dict):
        raise BankError("pack.yaml must be a top-level mapping of pack metadata")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BankError("pack.yaml: 'name' must be a non-empty string")
    return data
