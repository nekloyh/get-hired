"""Frozen concept-retrieval eval set + hit@1 with a Wilson interval (R-15, GH #70).

The 2026-07-11 retrieval audit derived its eval *live* from ``questions.yaml`` — queries from
``follow_up_seeds``, ground truth from ``expected_concepts`` — which produced two defects the
calibration bench had already been hardened against (ADR 0009 addendum b):

* **A one-way label ratchet.** The agent running the eval judged four of its own misses to be label
  defects, edited ``expected_concepts``, and reported 47/50 instead of 43/50. Self-graded, upward.
* **A moving denominator.** The audit measured 50 lookups; the same enumeration on the bank at
  184f5a2 yields 59. A published retrieval score was not comparable to itself across commits.

Everything here follows from severing the eval from the bank: ``data/bench/retrieval-labels.yaml``
holds **literal** queries, **literal** filters and **literal** labels, this module only reads it, and
a test pins the file's sha256. Nothing that computes a score is allowed to write it — which is why
harvesting new live queries emits stubs to stdout rather than appending rows.

Store construction lives in ``scripts/retrieval_eval.py``, not here: the lookup is injected, so the
whole aggregation is exercised in the default test suite against ``InMemoryConceptStore`` without
the optional Chroma/sentence-transformers extras.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .concepts import SEED_CONCEPTS, ConceptLookup

# The AC's goal for the set. Live queries are the only ones with production shape (a seed row's
# query is still the audit's template), and there are three of them today — so the report says how
# far short it is rather than letting a wide interval read as a result.
TARGET_SET_SIZE = 150

_VALID_SOURCES = ("seed", "live")
_REQUIRED_KEYS = ("id", "source", "origin", "skill", "language", "query", "expected")


class RetrievalEvalError(ValueError):
    """The frozen retrieval-labels file is malformed. Same fail-loud voice as :class:`BankError`."""


# data/bench/retrieval-labels.yaml lives at the repo root next to cases.yaml (a content pack), not
# inside the package — same idiom as `bench._default_cases_path`.
DEFAULT_LABELS_PATH: Path = (
    resources.files("interview_coach")  # type: ignore[attr-defined]  # always a real file, never a zip member
    .joinpath("..", "..", "data", "bench", "retrieval-labels.yaml")
    .resolve()
)

# The lookup under test: (query, skill, language) -> ConceptLookup. Injected rather than built here
# so the aggregation is testable with no rag extras installed, and so an eval can never quietly
# measure a different store than the one it names in its own header.
LookupFn = Callable[[str, str | None, str | None], ConceptLookup]


@dataclass(frozen=True)
class RetrievalCase:
    """One frozen ``lookup_concept`` call plus its hand label.

    ``query``/``skill``/``language`` reproduce the call literally. Recomputing any of them at run
    time — re-joining a seed with its question, or deriving the language filter from the shelf — is
    what let the eval drift with the bank in the first place.
    """

    case_id: str
    query: str
    skill: str | None
    language: str | None
    expected: tuple[str, ...]
    source: str
    origin: str

    @property
    def is_labelled(self) -> bool:
        return bool(self.expected)


@dataclass(frozen=True)
class RetrievalOutcome:
    case: RetrievalCase
    hit_id: str
    score: float | None

    @property
    def hit(self) -> bool:
        return self.hit_id in self.case.expected


@dataclass(frozen=True)
class RetrievalReport:
    """Aggregate over one replay of the frozen set.

    ``unlabelled`` and ``errors`` are reported but kept OUT of the denominator, for different
    reasons. An unlabelled row counted as a miss would make hit@1 fall with every harvest, creating
    pressure to label optimistically — the ratchet, re-entering through the door marked "coverage".
    An unservable lookup is a shelf failure, not a ranking failure, and blaming the ranker for a note
    that does not exist is the mirror-image error.
    """

    outcomes: tuple[RetrievalOutcome, ...] = ()
    unlabelled: tuple[RetrievalCase, ...] = ()
    errors: tuple[tuple[RetrievalCase, str], ...] = ()

    @property
    def n_scored(self) -> int:
        return len(self.outcomes)

    @property
    def hits(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.hit)

    @property
    def misses(self) -> tuple[RetrievalOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.hit)

    @property
    def hit_rate(self) -> float:
        # Not `hits / max(1, n)`. A defensive divisor would print 0.0% as though it had been
        # measured — the same vacuous-green failure `bench_passed` guards against with its
        # non-empty check.
        self._require_scored()
        return self.hits / self.n_scored

    @property
    def interval(self) -> tuple[float, float]:
        self._require_scored()
        return wilson_interval(self.hits, self.n_scored)

    def _require_scored(self) -> None:
        if not self.outcomes:
            raise ValueError("no labelled cases were scored — there is no hit rate to report")

    @property
    def by_skill(self) -> dict[str, tuple[int, int]]:
        return self._grouped(lambda case: case.skill or "any")

    @property
    def by_source(self) -> dict[str, tuple[int, int]]:
        """Seed vs live, kept apart on purpose.

        The live rows were labelled by the same agent that ran the first eval and their labels agree
        with the hit the ranker recorded, so they cannot falsify it. Folding three self-confirming
        rows into one headline number hides that; two numbers side by side do not.
        """
        return self._grouped(lambda case: case.source)

    def _grouped(self, key: Callable[[RetrievalCase], str]) -> dict[str, tuple[int, int]]:
        grouped: dict[str, tuple[int, int]] = {}
        for outcome in self.outcomes:
            hits, total = grouped.get(key(outcome.case), (0, 0))
            grouped[key(outcome.case)] = (hits + int(outcome.hit), total + 1)
        return grouped


def labels_checksum(path: str | Path | None = None) -> str:
    """sha256 of the labels file's raw bytes.

    Raw bytes, not parsed content: the header comments are where the provenance and the ratchet
    warning live, so quietly rewriting them has to be as red as quietly rewriting a label.
    """
    target = Path(path) if path is not None else DEFAULT_LABELS_PATH
    return hashlib.sha256(target.read_bytes()).hexdigest()


def load_retrieval_labels(path: str | Path | None = None) -> tuple[RetrievalCase, ...]:
    """Load the frozen eval set. Reads YAML and nothing else — never the question bank."""
    target = Path(path) if path is not None else DEFAULT_LABELS_PATH
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping) or not isinstance(data.get("cases"), list):
        raise RetrievalEvalError(f"{target}: expected a mapping with a `cases` list")
    cases: list[RetrievalCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(data["cases"]):
        if not isinstance(raw, Mapping):
            raise RetrievalEvalError(f"{target}: case #{index} is not a mapping")
        # Every key is required, `skill` and `language` included even when null: defaulting an
        # absent language to None would silently restore the audit's unfiltered call — a call shape
        # production never makes (ADR 0007) — with no diff to point at.
        missing = [key for key in _REQUIRED_KEYS if key not in raw]
        if missing:
            raise RetrievalEvalError(f"{target}: case #{index} is missing required key(s): {', '.join(missing)}")
        case_id = str(raw["id"])
        if case_id in seen:
            raise RetrievalEvalError(f"{target}: duplicate case id {case_id!r}")
        seen.add(case_id)
        source = str(raw["source"])
        if source not in _VALID_SOURCES:
            raise RetrievalEvalError(
                f"{target}: case {case_id!r} has source {source!r}, expected one of {_VALID_SOURCES}"
            )
        expected = raw["expected"] or []
        if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
            raise RetrievalEvalError(f"{target}: case {case_id!r} `expected` must be a list of concept note ids")
        cases.append(
            RetrievalCase(
                case_id=case_id,
                query=str(raw["query"]),
                skill=None if raw["skill"] is None else str(raw["skill"]),
                language=None if raw["language"] is None else str(raw["language"]),
                expected=tuple(expected),
                source=source,
                origin=str(raw["origin"]),
            )
        )
    return tuple(cases)


def unknown_expected_concepts(cases: Iterable[RetrievalCase]) -> tuple[str, ...]:
    """Labelled note ids that are no longer on the concept shelf.

    The frozen file is otherwise embedder- and bank-independent — a row is (query, filters, expected
    ids), so re-ingesting under a different embedder cannot invalidate it. Renaming an id in
    ``data/concepts.yaml`` *can*: every label pointing at the old id becomes a permanent miss that
    reads exactly like a retrieval regression. Surfaced, not silently scored.
    """
    on_shelf = {note.id for note in SEED_CONCEPTS}
    return tuple(sorted({cid for case in cases for cid in case.expected if cid not in on_shelf}))


def evaluate_retrieval(cases: Iterable[RetrievalCase], lookup: LookupFn) -> RetrievalReport:
    """Replay every labelled case through ``lookup`` with its **frozen** filters."""
    outcomes: list[RetrievalOutcome] = []
    unlabelled: list[RetrievalCase] = []
    errors: list[tuple[RetrievalCase, str]] = []
    for case in cases:
        if not case.is_labelled:
            unlabelled.append(case)
            continue
        try:
            result = lookup(case.query, case.skill, case.language)
        except LookupError as err:
            errors.append((case, str(err)))
            continue
        outcomes.append(RetrievalOutcome(case=case, hit_id=result.note.id, score=result.score))
    return RetrievalReport(outcomes=tuple(outcomes), unlabelled=tuple(unlabelled), errors=tuple(errors))


def wilson_interval(successes: int, n: int, *, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Wilson rather than the normal approximation because the set is small and will stay small for a
    while: at 0/10 or 10/10 the Wald interval collapses to a point and reports a ten-sample result
    as certainty. A wrong CI is worse than none — it launders a small sample as precision.
    """
    if n <= 0:
        raise ValueError(f"n must be > 0 to form a confidence interval, got {n}")
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be in [0, {n}], got {successes}")
    z = statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    phat = successes / n
    denominator = 1 + z**2 / n
    centre = (phat + z**2 / (2 * n)) / denominator
    half = z / denominator * ((phat * (1 - phat) / n + z**2 / (4 * n**2)) ** 0.5)
    return (max(0.0, centre - half), min(1.0, centre + half))


def render_retrieval_report(report: RetrievalReport, *, store: str, embedding_model: str, checksum: str) -> str:
    """Markdown report. Names the store, the embedder and the label checksum in its own header —
    a retrieval number that does not say what produced it is not comparable to the next one."""
    lines = [
        "# Concept retrieval eval — frozen label set (R-15)",
        "",
        f"Store: `{store}`; embedder: `{embedding_model}`.",
        f"Labels: `data/bench/retrieval-labels.yaml` sha256 `{checksum}`.",
        "",
    ]
    if report.n_scored == 0:
        lines += [
            "**no labelled cases were scored** — nothing to report.",
            f"({len(report.unlabelled)} unlabelled, {len(report.errors)} unservable.)",
            "",
        ]
    else:
        lo, hi = report.interval
        lines += [
            f"## hit@1: {report.hits}/{report.n_scored} ({report.hit_rate:.1%})",
            "",
            f"Wilson 95% CI: [{lo:.1%}, {hi:.1%}].",
            "",
        ]
        if report.n_scored < TARGET_SET_SIZE:
            lines += [
                f"> **Small sample.** n={report.n_scored} — the target is {TARGET_SET_SIZE}+. This "
                "interval is wide and a change of +/-1 hit moves it materially; do not read a "
                "difference between two runs of this size as a regression.",
                "",
            ]
        lines += ["| Source | hits | rate |", "| --- | ---: | ---: |"]
        for source, (hits, total) in sorted(report.by_source.items()):
            lines.append(f"| {source} | {hits}/{total} | {hits / total:.0%} |")
        lines += ["", "| Skill | hits | rate |", "| --- | ---: | ---: |"]
        for skill, (hits, total) in sorted(report.by_skill.items()):
            lines.append(f"| {skill} | {hits}/{total} | {hits / total:.0%} |")
        lines.append("")
    if report.misses:
        lines += ["### Misses", ""]
        for miss in report.misses:
            score = "n/a" if miss.score is None else f"{miss.score:.3f}"
            lines.append(
                f"- `{miss.case.case_id}` ({miss.case.source}) -> `{miss.hit_id}` (score {score}); "
                f"expected one of `{', '.join(miss.case.expected)}`"
            )
        lines.append("")
    if report.unlabelled:
        lines += [
            f"### Unlabelled ({len(report.unlabelled)}) — reported, never scored",
            "",
        ]
        lines += [f"- `{case.case_id}`: `{case.query}`" for case in report.unlabelled]
        lines.append("")
    if report.errors:
        lines += [f"### Unservable ({len(report.errors)}) — the filter matched no note", ""]
        lines += [f"- `{case.case_id}`: {err}" for case, err in report.errors]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- harvesting live queries (stdout only, by construction) ---------------------------------------


@dataclass(frozen=True)
class HarvestedLookup:
    """One logged production lookup, recovered from a Session artifact."""

    query: str
    skill: str | None
    language: str | None
    origin: str


# The filter-bearing export render (see `exporter._append_transcript`). `any` is how a null filter is
# printed, so it maps back to None rather than to a literal skill named "any".
_MD_LOOKUP_RE = re.compile(
    r"^Concept lookup: `(?P<query>.+?)` \(skill=`(?P<skill>[^`]*)`, language=`(?P<language>[^`]*)`\) -> `[^`]*`$"
)
# Exports written before this issue landed carry no filters. Replaying such a query would reproduce
# the audit's unfiltered-call defect, so it is harvested with unknown filters that a human must fill.
_MD_LEGACY_LOOKUP_RE = re.compile(r"^Concept lookup: `(?P<query>.+?)` -> `[^`]*`$")


def _unfilter(value: str) -> str | None:
    return None if value == "any" else value


def harvest_lookup_calls(root: str | Path, known: Iterable[RetrievalCase] = ()) -> tuple[HarvestedLookup, ...]:
    """Scan Markdown exports and JSON Session/replay artifacts for logged ``concept_lookup_query``.

    De-duplicated on (query, skill, language) and against the queries already frozen, so a re-harvest
    of the same export directory proposes nothing.
    """
    directory = Path(root)
    frozen = {case.query for case in known}
    seen: set[tuple[str, str | None, str | None]] = set()
    harvested: list[HarvestedLookup] = []

    def admit(query: str, skill: str | None, language: str | None, origin: str) -> None:
        key = (query, skill, language)
        if query in frozen or key in seen:
            return
        seen.add(key)
        harvested.append(HarvestedLookup(query=query, skill=skill, language=language, origin=origin))

    for path in sorted(directory.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = _MD_LOOKUP_RE.match(line.strip())
            if match:
                admit(
                    _unescape_md(match["query"]),
                    _unfilter(match["skill"]),
                    _unfilter(match["language"]),
                    f"{path.name}:{number}",
                )
                continue
            legacy = _MD_LEGACY_LOOKUP_RE.match(line.strip())
            if legacy:
                admit(
                    _unescape_md(legacy["query"]),
                    None,
                    None,
                    f"{path.name}:{number} (pre-R-15 export, FILTERS UNKNOWN)",
                )
    for path in sorted(directory.rglob("*.json")):
        for trace, where in _traces(json.loads(path.read_text(encoding="utf-8"))):
            query = trace.get("concept_lookup_query")
            if isinstance(query, str) and query:
                admit(
                    query,
                    trace.get("concept_lookup_skill"),
                    trace.get("concept_lookup_language"),
                    f"{path.name}{where}",
                )
    return tuple(harvested)


def _traces(node: Any, where: str = "") -> list[tuple[Mapping[str, Any], str]]:
    """Every ``trace`` mapping anywhere in a JSON artifact, with a path for provenance.

    Structural rather than schema-bound: replay artifacts nest the state under ``final_state``, a
    raw checkpoint does not, and neither shape is this module's to own.
    """
    found: list[tuple[Mapping[str, Any], str]] = []
    if isinstance(node, Mapping):
        trace = node.get("trace")
        if isinstance(trace, Mapping):
            found.append((trace, f"{where}.trace"))
        for key, value in node.items():
            found.extend(_traces(value, f"{where}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_traces(value, f"{where}[{index}]"))
    return found


def _unescape_md(text: str) -> str:
    # `exporter._md` escapes a literal pipe for the transcript tables; a replayed query has to be
    # byte-identical to what the model actually asked or it is not the production call.
    return text.replace("\\|", "|")


def render_harvest_stubs(harvested: Sequence[HarvestedLookup]) -> str:
    """YAML stubs for a human to label. Printed, never written.

    Two reasons this must stay stdout-only: the tool that computes the score must not be able to
    write the file it is graded against, and ``data/exports/`` is Candidate transcript data the repo
    deliberately refuses to hold — a human has to read every string before it becomes repo content.
    """
    if not harvested:
        return "# nothing new to harvest: every logged query is already in the frozen set.\n"
    lines = [
        "# PENDING HUMAN VALIDATION — not loaded until moved into data/bench/retrieval-labels.yaml.",
        "# Redact anything that identifies a Candidate, then label `expected` FROM THE CONCEPT SHELF",
        "# — never from what the store returned for this query.",
        "cases:",
    ]
    for index, item in enumerate(harvested, start=1):
        skill = "null" if item.skill is None else json.dumps(item.skill)
        language = "null" if item.language is None else json.dumps(item.language)
        lines += [
            f"  - id: live-{index:04d}",
            "    source: live",
            f"    origin: {json.dumps(item.origin)}",
            f"    skill: {skill}",
            f"    language: {language}",
            f"    query: {json.dumps(item.query, ensure_ascii=False)}",
            "    expected: []  # TODO: label by hand",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"
