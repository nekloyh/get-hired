from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from interview_coach.concepts import (
    SEED_CONCEPTS,
    ConceptLookup,
    ConceptNote,
    InMemoryConceptStore,
    lookup_concept,
)
from interview_coach.exporter import render_session_markdown
from interview_coach.retrieval_eval import (
    DEFAULT_LABELS_PATH,
    TARGET_SET_SIZE,
    RetrievalCase,
    RetrievalEvalError,
    evaluate_retrieval,
    harvest_lookup_calls,
    labels_checksum,
    load_retrieval_labels,
    render_harvest_stubs,
    render_retrieval_report,
    unknown_expected_concepts,
    wilson_interval,
)

# The pin. Editing a label without editing this line turns CI red; editing both is a two-place diff
# a reviewer cannot miss. Recompute with:
#   sha256sum data/bench/retrieval-labels.yaml
_PINNED_SHA256 = "9b37849c44f2f2aaeef4dd28e66ecdd44b9b59b85c417edc736ca07eeb82b4d0"

# 59 seed rows enumerated from the bank at 184f5a2 + 3 live rows from the committed replay artifact.
# Pinned separately from the checksum so a reader of a failure sees WHICH invariant moved.
_FROZEN_CASE_COUNT = 62


def _note(note_id, skill="mlops", language="en", content="content", tags=()):
    return ConceptNote(id=note_id, skill=skill, title=note_id, content=content, language=language, tags=tags)


def _case(case_id="c1", *, query="q", skill="mlops", language=None, expected=("a",), source="seed"):
    return RetrievalCase(
        case_id=case_id,
        query=query,
        skill=skill,
        language=language,
        expected=tuple(expected),
        source=source,
        origin="test",
    )


def _store_lookup(store):
    def lookup(query, skill, language):
        return lookup_concept(store, query, skill=skill, language=language)

    return lookup


def _fixed_lookup(note_id):
    def lookup(query, skill, language):
        return ConceptLookup(note=_note(note_id), score=0.5)

    return lookup


# --- the freeze (AC-a) ---------------------------------------------------------------------------


def test_the_eval_set_is_frozen_not_derived_from_the_live_bank(monkeypatch):
    """The whole point of R-15: the eval must not move when the question bank moves.

    The 2026-07-11 audit measured 50 lookups; the same live enumeration on today's bank yields 59,
    because `follow_up_seeds` grew and the eval silently followed. Blowing up every path back to the
    bank makes "derived" impossible rather than merely discouraged.
    """

    def boom(*args, **kwargs):
        raise AssertionError("the frozen eval set must not read the live question bank")

    monkeypatch.setattr("interview_coach.bank.load_questions", boom)
    monkeypatch.setattr("interview_coach.seeds.load_questions", boom, raising=False)

    cases = load_retrieval_labels()

    assert len(cases) == _FROZEN_CASE_COUNT


def test_a_query_is_a_literal_string_not_a_template_rejoined_at_run_time(tmp_path):
    """A row's query must survive verbatim, including text that exists nowhere in the bank."""
    path = tmp_path / "labels.yaml"
    path.write_text(
        "version: 1\ncases:\n"
        '  - id: x\n    source: seed\n    origin: o\n    skill: "mlops"\n    language: null\n'
        '    query: "zzz-not-in-any-bank-question"\n    expected: [mlops_drift_monitoring]\n',
        encoding="utf-8",
    )

    (case,) = load_retrieval_labels(path)

    assert case.query == "zzz-not-in-any-bank-question"


def test_frozen_labels_checksum_matches_the_pin():
    assert labels_checksum(DEFAULT_LABELS_PATH) == _PINNED_SHA256


def test_the_checksum_changes_when_a_single_label_is_edited(tmp_path):
    """The exact 43->47 move: one concept id appended to one row's `expected`."""
    original = DEFAULT_LABELS_PATH.read_text(encoding="utf-8")
    copy = tmp_path / "labels.yaml"
    copy.write_text(original, encoding="utf-8")
    assert labels_checksum(copy) == _PINNED_SHA256

    copy.write_text(
        original.replace(
            "    expected: [mlops_drift_monitoring]\n",
            "    expected: [mlops_drift_monitoring, mlops_ci_cd_models]\n",
            1,
        ),
        encoding="utf-8",
    )

    assert labels_checksum(copy) != _PINNED_SHA256


def test_the_checksum_changes_when_only_a_comment_is_edited(tmp_path):
    """Raw bytes, not parsed content: the header comments carry the provenance and the ratchet
    warning, so quietly rewriting them must be as red as quietly rewriting a label."""
    copy = tmp_path / "labels.yaml"
    copy.write_text(
        "# a comment\n" + DEFAULT_LABELS_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert labels_checksum(copy) != _PINNED_SHA256


# --- loader validation ---------------------------------------------------------------------------


_ROW_KEYS = {
    "id": "x",
    "source": "seed",
    "origin": "o",
    "skill": "null",
    "language": "null",
    "query": '"q"',
    "expected": "[a]",
}


def _row(drop=(), **overrides):
    keys = {**_ROW_KEYS, **overrides}
    body = "".join(f"    {k}: {v}\n" for k, v in keys.items() if k != "id" and k not in drop)
    return f"  - id: {keys['id']}\n{body}"


def _write(tmp_path, rows: str):
    path = tmp_path / "labels.yaml"
    path.write_text(f"version: 1\ncases:\n{rows}", encoding="utf-8")
    return path


def test_a_row_missing_the_language_key_is_rejected(tmp_path):
    """Defaulting an absent `language` to None would silently re-introduce the audit's third defect
    (an unfiltered call production never makes), so the key is required even when it is null."""
    path = _write(tmp_path, _row(drop=("language",)))

    with pytest.raises(RetrievalEvalError, match="language"):
        load_retrieval_labels(path)


def test_a_row_missing_the_skill_key_is_rejected(tmp_path):
    path = _write(tmp_path, _row(drop=("skill",)))

    with pytest.raises(RetrievalEvalError, match="skill"):
        load_retrieval_labels(path)


def test_duplicate_case_ids_are_rejected(tmp_path):
    path = _write(tmp_path, _row() + _row())

    with pytest.raises(RetrievalEvalError, match="duplicate"):
        load_retrieval_labels(path)


def test_an_unknown_source_is_rejected(tmp_path):
    path = _write(tmp_path, _row(source="synthetic"))

    with pytest.raises(RetrievalEvalError, match="source"):
        load_retrieval_labels(path)


@pytest.mark.parametrize(
    "literal",
    ["", "{}", "0", '""'],
    ids=["bare-key", "empty-mapping", "number", "empty-string"],
)
def test_a_malformed_expected_is_rejected_not_silently_read_as_unlabelled(tmp_path, literal):
    """The silent-denominator-shrink hole, and it was open.

    `expected = raw["expected"] or []` short-circuits on EVERY falsy value before the isinstance
    check ever runs, so each of these four parsed as "harvested, not yet labelled" — reported,
    never scored, gone from the denominator without a word. A typo'd row quietly making hit@1 a
    smaller measurement is precisely the class R-15 exists to fence, and the loader's docstring
    already promised to fail loud on it. `[]` stays the one way to say unlabelled, and it has to be
    written deliberately.
    """
    path = _write(tmp_path, _row(expected=literal))

    with pytest.raises(RetrievalEvalError, match="expected"):
        load_retrieval_labels(path)


def test_an_explicit_empty_list_is_the_one_way_to_say_unlabelled(tmp_path):
    """The control for the four above: `[]` must still load, or the harvest stubs (`expected: []`)
    would be unloadable and the whole pending-file convention would break."""
    (case,) = load_retrieval_labels(_write(tmp_path, _row(expected="[]")))

    assert case.expected == ()
    assert not case.is_labelled


def test_the_frozen_file_writes_every_expected_as_an_explicit_list():
    """Belt and braces on the loader fix: no frozen row may rely on falsy-to-unlabelled coercion,
    so every one of the 62 must round-trip as a real list — labelled or explicitly empty."""
    cases = load_retrieval_labels()

    assert len(cases) == _FROZEN_CASE_COUNT
    assert all(isinstance(case.expected, tuple) for case in cases)
    assert all(case.is_labelled for case in cases)


def test_a_complete_row_loads(tmp_path):
    """The control for the four rejection tests above: the fixture is only wrong where they make it
    wrong, so `pytest.raises` cannot be passing for an unrelated reason."""
    (case,) = load_retrieval_labels(_write(tmp_path, _row()))

    assert (case.case_id, case.skill, case.language, case.expected) == ("x", None, None, ("a",))


def test_the_frozen_file_names_only_concepts_that_are_on_the_shelf():
    """A rename in data/concepts.yaml turns every label pointing at the old id into a permanent
    miss, which reads exactly like a retrieval regression. This is the only coupling between the
    frozen file and the live content, and it is surfaced rather than silently scored."""
    assert unknown_expected_concepts(load_retrieval_labels()) == ()


def test_unknown_expected_concepts_reports_a_label_that_left_the_shelf():
    assert unknown_expected_concepts((_case(expected=("mlops_no_such_note",)),)) == ("mlops_no_such_note",)


# --- production call shape (AC-b, ADR 0007) -------------------------------------------------------


def test_a_live_case_is_replayed_with_the_filters_it_was_logged_with():
    """The audit's third defect: its script called lookup_concept(store, query, skill=skill) with no
    language, a call production never makes. Replaying a harvested query without its frozen filters
    reproduces exactly that."""
    store = InMemoryConceptStore([_note("mlops_drift_monitoring"), _note("vi_note", skill="mlops", language="vi")])

    evaluate_retrieval(
        (_case(query="drift", skill="mlops", language="vi", expected=("vi_note",), source="live"),),
        _store_lookup(store),
    )

    assert store.lookup_calls[-1] == {"query": "drift", "skill": "mlops", "language": "vi"}


def test_the_vietnamese_seed_rows_carry_the_vi_language_filter():
    """`_preferred_lookup_language(None, "vietnamese_nlp", "en")` is "vi" (ADR 0007). The frozen rows
    must carry that answer, or they were generated by copying the old unfiltered script."""
    vn_rows = [c for c in load_retrieval_labels() if c.skill == "vietnamese_nlp"]

    assert vn_rows
    assert {c.language for c in vn_rows} == {"vi"}


def test_the_vi_filter_is_candidate_preserving_on_the_vietnamese_shelf_today():
    """The frozen file's header claims the vi filter changes no current number, and this is why:
    every note on that shelf is already `vi`, so the filter selects the same candidates as the Skill
    filter alone (measured: identical hit ids with and without it, 59/62 either way).

    The moment an English note lands on the vietnamese_nlp shelf that stops being true and this test
    goes red — which is exactly when a reviewer needs to know that the frozen filter has become
    load-bearing and the published number may move for a reason that is not a ranker change.
    """
    shelf = [note for note in SEED_CONCEPTS if note.skill == "vietnamese_nlp"]

    assert shelf
    assert {note.language for note in shelf} == {"vi"}


def test_the_english_seed_rows_carry_no_language_filter():
    """The mirror check: the same function returns None off the vietnamese_nlp shelf, so a blanket
    language="vi" everywhere would be just as wrong as none at all."""
    other = [c for c in load_retrieval_labels() if c.source == "seed" and c.skill != "vietnamese_nlp"]

    assert other
    assert {c.language for c in other} == {None}


def test_the_vi_filter_returns_the_same_hit_ids_it_would_without_the_filter():
    """The measurement the test above only claims in prose.

    The frozen file's header says the vi filter "changes no current number" because every note on
    the vietnamese_nlp shelf is already `language: vi`. That was an unenforced assertion in a
    docstring, which is how a caveat rots. Here it is a check: replay the whole frozen set twice,
    once as frozen and once with every language filter stripped, and compare hit ids row by row.

    Two failure directions, both worth a red. If the shelf gains an English note the filtered and
    unfiltered rankings diverge and the frozen filter becomes load-bearing — a reviewer needs to know
    the published number can now move for a reason that is not a ranker change. If instead the filter
    stops being applied at all, this goes green while `test_a_live_case_is_replayed_with_the_filters
    _it_was_logged_with` goes red, which is the pair reading correctly.
    """
    cases = load_retrieval_labels()
    store = InMemoryConceptStore(SEED_CONCEPTS)

    frozen = evaluate_retrieval(cases, _store_lookup(store))
    unfiltered = evaluate_retrieval(tuple(replace(c, language=None) for c in cases), _store_lookup(store))

    assert [o.hit_id for o in frozen.outcomes] == [o.hit_id for o in unfiltered.outcomes]
    assert (frozen.hits, frozen.n_scored) == (unfiltered.hits, unfiltered.n_scored) == (59, 62)


def test_no_frozen_row_needs_the_production_widening_retry():
    """The narrow half of the fidelity claim, pinned.

    Production reaches the store through `interviewer._lookup_with_widening`, which retries once
    with `language=None` on LookupError; `evaluate_retrieval` calls `lookup_concept` straight and
    files a LookupError as unservable instead. Those two agree exactly as long as no frozen row ever
    takes the widening branch — i.e. as long as `errors` is empty. It is, for all 62 rows, so the
    replay is the production call today. The day a row becomes unservable this goes red, which is
    the day the divergence starts to matter and someone has to decide which behaviour the eval wants.
    """
    report = evaluate_retrieval(load_retrieval_labels(), _store_lookup(InMemoryConceptStore(SEED_CONCEPTS)))

    assert report.errors == ()
    assert report.unlabelled == ()


# --- the headline number, scored end to end ------------------------------------------------------


def test_the_frozen_set_is_fifty_nine_seed_rows_and_three_live_rows():
    """The 59/3 split is load-bearing and was previously only prose. 59 is the seed enumeration off
    the bank at 184f5a2 — the number that shows the 2026-07-11 audit's 50 had drifted. 3 is how far
    the production-shaped half actually reaches, and `by_source` exists to keep those two apart.
    Asserting only the total 62 lets every row be relabelled `seed` with nothing going red."""
    counts = Counter(case.source for case in load_retrieval_labels())

    assert counts == {"seed": 59, "live": 3}
    assert sum(counts.values()) == _FROZEN_CASE_COUNT


def test_the_frozen_set_scores_fifty_nine_of_sixty_two_on_the_in_memory_shelf():
    """The number this whole issue exists to protect, actually computed in CI.

    Every other scoring test runs on hand-built two-note fixtures with a single-element `expected`,
    so the aggregation was pinned but the *headline* was not: narrowing the hit predicate from
    "the top note is one of the acceptable labels" to "the top note is the first label" left the
    whole suite green while this moved 59/62 (95.2%) -> 48/62 (77.4%). The in-memory shelf is used
    deliberately — it needs no rag extras and the whole replay takes ~0.01s — so the guard runs on
    every default `pytest -q`, not only where chromadb happens to be installed.

    This is a floor, not the production path: `scripts/retrieval_eval.py` measures Chroma + BGE and
    stamps which store it used. If a concepts.yaml edit moves this number, that is the eval doing
    its job — re-measure and update the literal in the same diff.
    """
    report = evaluate_retrieval(load_retrieval_labels(), _store_lookup(InMemoryConceptStore(SEED_CONCEPTS)))

    assert (report.hits, report.n_scored) == (59, 62)
    assert report.hit_rate == pytest.approx(0.951612903225806, abs=1e-12)
    assert report.by_source == {"seed": (56, 59), "live": (3, 3)}


def test_multi_label_rows_are_where_the_headline_lives():
    """Why "acceptable hits" is plural, quantified on the real set.

    21 of the 62 frozen rows carry 2-4 acceptable ids — the 2026-07-11 ratchet is largely *made* of
    such appends (+mlops_experiment_tracking, +mlops_data_validation, +vietnamese_nlp_vncorenlp) —
    and 11 of the 59 hits land on a label that is not the first entry. Those 11 are the exact
    distance between 59/62 and 48/62, so a reader who wants to know how much of the headline rests
    on multi-label semantics is looking at a measured number rather than at this sentence.
    """
    cases = load_retrieval_labels()
    report = evaluate_retrieval(cases, _store_lookup(InMemoryConceptStore(SEED_CONCEPTS)))

    assert sum(1 for case in cases if len(case.expected) > 1) == 21
    assert sum(1 for o in report.outcomes if o.hit and o.hit_id != o.case.expected[0]) == 11
    assert sum(1 for o in report.outcomes if o.hit_id == o.case.expected[0]) == 48


def test_a_hit_on_any_acceptable_label_counts_not_only_the_first():
    """The predicate itself, away from the shelf: `expected` is a set of acceptable hits, and the
    order they were written in carries no meaning."""
    cases = (
        _case("first", expected=("a", "b")),
        _case("second", expected=("b", "a")),
        _case("neither", expected=("b", "c")),
    )

    report = evaluate_retrieval(cases, _fixed_lookup("a"))

    assert {o.case.case_id: o.hit for o in report.outcomes} == {"first": True, "second": True, "neither": False}


# --- scoring -------------------------------------------------------------------------------------


def test_hit_at_1_counts_only_the_top_note():
    store = InMemoryConceptStore(
        [_note("right", content="drift monitoring retraining"), _note("wrong", content="rollout canary")]
    )
    cases = (
        _case("a", query="drift monitoring retraining", expected=("right",)),
        _case("b", query="rollout canary", expected=("right",)),
    )

    report = evaluate_retrieval(cases, _store_lookup(store))

    assert (report.hits, report.n_scored) == (1, 2)
    assert [m.case.case_id for m in report.misses] == ["b"]


def test_unlabelled_cases_are_reported_but_never_scored():
    """A harvested-but-unlabelled backlog must not drag hit@1 down: that would create pressure to
    label optimistically, which is the ratchet coming back through the door marked 'coverage'."""
    report = evaluate_retrieval((_case("a", expected=("a",)), _case("b", expected=())), _fixed_lookup("a"))

    assert [c.case_id for c in report.unlabelled] == ["b"]
    assert (report.hits, report.n_scored) == (1, 1)


def test_a_lookup_that_cannot_be_served_is_an_error_not_a_miss():
    """An empty filter result is a shelf failure, not a ranking failure; folding it into the miss
    column would blame the ranker for a note that does not exist."""

    def lookup(query, skill, language):
        raise LookupError("no concept notes match")

    report = evaluate_retrieval((_case("a"),), lookup)

    assert [c.case_id for c, _ in report.errors] == ["a"]
    assert report.n_scored == 0


def test_per_source_hit_rates_are_reported_separately():
    """The three live rows were labelled by the agent that ran the eval and agree with the hit the
    ranker recorded, so they cannot falsify it. Folding them into one headline number hides that."""
    cases = (_case("s", expected=("a",), source="seed"), _case("l", expected=("b",), source="live"))

    report = evaluate_retrieval(cases, _fixed_lookup("a"))

    assert report.by_source == {"seed": (1, 1), "live": (0, 1)}


def test_per_skill_hit_rates_are_reported():
    cases = (_case("a", skill="mlops", expected=("a",)), _case("b", skill="deep_learning", expected=("z",)))

    report = evaluate_retrieval(cases, _fixed_lookup("a"))

    assert report.by_skill == {"mlops": (1, 1), "deep_learning": (0, 1)}


def test_an_unfiltered_case_is_grouped_under_any_not_under_none():
    """`case.skill or "any"` is the only place a null Skill filter gets a name. Left as None it
    would be an unsortable key next to the strings — `sorted(by_skill)` raises — so the fallback is
    load-bearing for the report, not cosmetic. "any" also matches how the export renders a null
    filter, which is what `_unfilter` reads back on harvest."""
    cases = (_case("a", skill=None, expected=("a",)), _case("b", skill="mlops", expected=("a",)))

    report = evaluate_retrieval(cases, _fixed_lookup("a"))

    assert report.by_skill == {"any": (1, 1), "mlops": (1, 1)}
    assert "| any | 1/1 |" in render_retrieval_report(report, store="memory", embedding_model="none", checksum="c")


# --- Wilson interval (AC-b) ----------------------------------------------------------------------


def test_wilson_interval_matches_published_endpoints():
    """The killer cases. Wald/normal-approximation — the common wrong implementation — returns
    (0.0, 0.0) and (1.0, 1.0) here: a 10-sample result laundered as certainty. These endpoints also
    catch a z of 2 instead of 1.959964 and a dropped z^2/4n^2 term."""
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.27753), abs=1e-5)
    assert wilson_interval(10, 10) == pytest.approx((0.72247, 1.0), abs=1e-5)


def test_wilson_interval_matches_interior_reference_points():
    """The two endpoints above are blind to the variance term, and that blindness was a real hole.

    At x=0 and x=n the factor `phat * (1 - phat)` is IDENTICALLY ZERO, so deleting it from the
    half-width leaves both of them — and mirror symmetry, and the narrows-with-n check — completely
    unchanged. The mutant survived the whole suite while the interval at the real operating point
    (59/62) collapsed from [86.7%, 98.3%] to [89.6%, 95.4%]: width 0.116 -> 0.058. Laundering a
    62-sample result as twice the precision it has is exactly what `wilson_interval`'s own docstring
    says Wilson is here to prevent, and hit@1-with-a-CI is this issue's stated deliverable. So the
    reference set needs at least one point where the term is non-zero.

    59/62 is the frozen set's live operating point; 5/10 is p-hat = 0.5, where the term is at its
    maximum. Both endpoints re-derived independently at 50 significant digits with `decimal` (z =
    1.9599639845400545345521376207289648827582310510462, the two-sided 95% normal quantile). The
    float path agrees to ~1e-16; 1e-12 is slack for that, and 0.029 clear of the mutant.
    """
    assert wilson_interval(59, 62) == pytest.approx((0.86711962072676038, 0.98340831414941929), abs=1e-12)
    assert wilson_interval(5, 10) == pytest.approx((0.23659309051256395, 0.76340690948743605), abs=1e-12)


def test_wilson_interval_is_mirror_symmetric():
    """lo(x, n) == 1 - hi(n-x, n) is an exact Wilson identity — a reference-free algebra check."""
    for n in (1, 7, 50):
        for x in range(n + 1):
            assert wilson_interval(x, n)[0] == pytest.approx(1 - wilson_interval(n - x, n)[1], abs=1e-12)


def test_wilson_interval_narrows_as_n_grows_at_fixed_p():
    def width(x, n):
        lo, hi = wilson_interval(x, n)
        return hi - lo

    assert width(47, 50) > width(470, 500)


def test_wilson_interval_is_clamped_to_the_unit_interval():
    """Wilson is algebraically inside [0, 1], but not in floating point: unclamped, `x=0, n=2` gives
    lo = -5.6e-17 and `x=9, n=9` gives hi = 1.0000000000000002. These two n are chosen because they
    are the small ones that actually escape — a probability printed as `-0.0%` is a bug report."""
    for n in (1, 2, 9, 62):
        for x in range(n + 1):
            lo, hi = wilson_interval(x, n)
            assert 0.0 <= lo <= hi <= 1.0


def test_wilson_interval_refuses_an_empty_sample():
    with pytest.raises(ValueError, match="n must be"):
        wilson_interval(0, 0)


def test_wilson_interval_refuses_more_successes_than_trials():
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(3, 2)


def test_hit_rate_refuses_to_report_on_an_empty_case_set():
    """Not `hits / max(1, n)`: a defensive divisor would print 0.0% as if it had been measured."""
    report = evaluate_retrieval((), _fixed_lookup("a"))

    with pytest.raises(ValueError, match="no labelled cases"):
        _ = report.hit_rate
    with pytest.raises(ValueError, match="no labelled cases"):
        _ = report.interval


# --- report rendering ----------------------------------------------------------------------------


def test_a_report_below_the_target_size_says_so():
    """The target is written out as a literal here on purpose: asserting `str(TARGET_SET_SIZE)`
    would follow the constant wherever it moved and pin nothing."""
    assert TARGET_SET_SIZE == 150
    report = evaluate_retrieval((_case("a", expected=("a",)),), _fixed_lookup("a"))

    text = render_retrieval_report(report, store="memory", embedding_model="none", checksum="abc")

    assert "150" in text
    assert "n=1" in text
    assert "Small sample" in text


def test_a_report_at_or_above_the_target_size_drops_the_small_sample_warning():
    """The other side of the branch: the warning must be a measurement, not decoration."""
    cases = tuple(_case(f"c{i}", expected=("a",)) for i in range(TARGET_SET_SIZE))

    text = render_retrieval_report(
        evaluate_retrieval(cases, _fixed_lookup("a")), store="memory", embedding_model="none", checksum="abc"
    )

    assert "Small sample" not in text


def test_the_report_stamps_the_labels_checksum_and_the_store_it_measured():
    """A published retrieval number that does not say which label file and which store produced it
    is not comparable to the next one."""
    report = evaluate_retrieval((_case("a", expected=("a",)),), _fixed_lookup("a"))

    text = render_retrieval_report(
        report, store="chroma", embedding_model="BAAI/bge-small-en-v1.5", checksum="deadbeef"
    )

    assert "deadbeef" in text
    assert "chroma" in text
    assert "BAAI/bge-small-en-v1.5" in text


def test_an_all_unlabelled_report_refuses_to_print_a_hit_rate():
    report = evaluate_retrieval((_case("a", expected=()),), _fixed_lookup("a"))

    text = render_retrieval_report(report, store="memory", embedding_model="none", checksum="abc")

    assert "no labelled cases" in text


def test_the_report_names_every_miss_and_what_the_ranker_returned_instead():
    """The misses section is the only part of the report anyone can act on: a bare 59/62 tells you
    a number moved, the miss list tells you which query and which wrong note. The whole block was
    deletable with the suite still green."""
    cases = (_case("hit", expected=("a",)), _case("gone", query="q2", expected=("x", "y"), source="live"))

    text = render_retrieval_report(
        evaluate_retrieval(cases, _fixed_lookup("a")), store="memory", embedding_model="none", checksum="abc"
    )

    assert "### Misses" in text
    assert "`gone` (live) -> `a` (score 0.500); expected one of `x, y`" in text
    assert "`hit`" not in text  # a hit is not a miss; listing it would make the section unreadable


def test_the_report_names_every_unservable_lookup():
    """An unservable row is out of the denominator, so it is invisible in the headline by design —
    which makes printing it the only thing that stops a shelf/filter break from reading as a quiet
    n going down. Deleting this section left the suite green."""

    def lookup(query, skill, language):
        raise LookupError("no concept notes match skill='ghost'")

    text = render_retrieval_report(
        evaluate_retrieval((_case("a"),), lookup), store="memory", embedding_model="none", checksum="abc"
    )

    assert "### Unservable (1)" in text
    assert "`a`: no concept notes match skill='ghost'" in text


# --- harvest (stdout only, never writes) ----------------------------------------------------------


def test_the_markdown_export_records_the_lookup_filters():
    """Without the filters in the export, every future harvest yields a bare query and replaying it
    reproduces the audit's unfiltered-call defect. This is the only coverage for that render: the
    serde golden fixture leaves concept_lookup_query null, so it carries no lookup line."""
    state = {
        "session_id": "s",
        "transcript": [
            {
                "skill": "mlops",
                "turns": [
                    {
                        "question": "q",
                        "answer": "a",
                        "evaluation": {},
                        "trace": {
                            "concept_lookup_query": "monitoring for drift",
                            "concept_lookup_skill": "mlops",
                            "concept_lookup_language": "vi",
                            "concept_hit_id": "mlops_drift_monitoring",
                        },
                    }
                ],
            }
        ],
    }

    text = render_session_markdown(state)

    assert "Concept lookup: `monitoring for drift` (skill=`mlops`, language=`vi`) -> `mlops_drift_monitoring`" in text


def test_the_harvester_reads_what_the_real_exporter_actually_writes(tmp_path):
    """The seam, round-tripped end to end instead of at both ends separately.

    `exporter._append_transcript` writes the lookup line and `_MD_LOOKUP_RE` parses it, each holding
    its own independent literal. The writer test above pins the render string and every harvest test
    hand-writes its own input, so the two literals were free to drift apart: changing the render's
    `(skill=...)` to `[skill=...]` and updating its pinning test in lockstep left the suite green
    while harvesting real export output returned nothing at all — the accumulation path toward the
    150+ target silently yielding zero forever. Nothing here is hand-written: the exporter produces
    the text, the harvester consumes it, and the query/filters have to survive the trip.
    """
    state = {
        "session_id": "s",
        "transcript": [
            {
                "skill": "vietnamese_nlp",
                "turns": [
                    {
                        "question": "q",
                        "answer": "a",
                        "evaluation": {},
                        "trace": {
                            "concept_lookup_query": "phân đoạn từ tiếng Việt | PhoBERT",
                            "concept_lookup_skill": "vietnamese_nlp",
                            "concept_lookup_language": "vi",
                            "concept_hit_id": "vietnamese_nlp_phobert",
                        },
                    },
                    {
                        "question": "q2",
                        "answer": "a2",
                        "evaluation": {},
                        "trace": {"concept_lookup_query": "drift", "concept_hit_id": "mlops_drift_monitoring"},
                    },
                ],
            }
        ],
    }
    (tmp_path / "export.md").write_text(render_session_markdown(state), encoding="utf-8")

    harvested = harvest_lookup_calls(tmp_path)

    # The pipe-bearing Vietnamese query survives `_md`'s escape; the second turn logged no filters,
    # so it comes back as the unfiltered shape a human must resolve before it can be frozen.
    assert {(h.query, h.skill, h.language) for h in harvested} == {
        ("phân đoạn từ tiếng Việt | PhoBERT", "vietnamese_nlp", "vi"),
        ("drift", None, None),
    }


def test_harvest_reads_markdown_exports_and_json_replays(tmp_path):
    (tmp_path / "a.md").write_text(
        "Concept lookup: `drift in prod` (skill=`mlops`, language=`any`) -> `mlops_drift_monitoring`\n",
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            {
                "final_state": {
                    "transcript": [
                        {
                            "turns": [
                                {
                                    "trace": {
                                        "concept_lookup_query": "phobert segmentation",
                                        "concept_lookup_skill": "vietnamese_nlp",
                                        "concept_lookup_language": "vi",
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    harvested = harvest_lookup_calls(tmp_path)

    assert {(h.query, h.skill, h.language) for h in harvested} == {
        ("drift in prod", "mlops", None),
        ("phobert segmentation", "vietnamese_nlp", "vi"),
    }


def test_harvest_unescapes_the_markdown_pipe_escape(tmp_path):
    """`exporter._md` writes `\\|` for a literal pipe; a harvested query must come back byte-identical
    to what the model actually asked, or the replay is not the production call."""
    (tmp_path / "a.md").write_text(
        "Concept lookup: `a \\| b` (skill=`mlops`, language=`any`) -> `x`\n", encoding="utf-8"
    )

    (harvested,) = harvest_lookup_calls(tmp_path)

    assert harvested.query == "a | b"


def test_harvest_flags_a_pre_r15_export_as_having_unknown_filters(tmp_path):
    """Exports written before the filter-bearing render carry only the query. Harvesting one and
    silently frozen with skill=null would replay it as the unfiltered call production never makes —
    so the stub says so, loudly, in the field a human has to read."""
    (tmp_path / "a.md").write_text("Concept lookup: `old bare query` -> `x`\n", encoding="utf-8")

    (harvested,) = harvest_lookup_calls(tmp_path)

    assert (harvested.query, harvested.skill, harvested.language) == ("old bare query", None, None)
    assert "FILTERS UNKNOWN" in harvested.origin


def test_harvest_skips_queries_already_frozen(tmp_path):
    (tmp_path / "a.md").write_text(
        "Concept lookup: `monitoring production models for data drift` (skill=`mlops`, language=`any`) -> `x`\n",
        encoding="utf-8",
    )

    assert harvest_lookup_calls(tmp_path, known=load_retrieval_labels()) == ()
    assert "nothing new to harvest" in render_harvest_stubs(())


def test_a_query_frozen_in_en_mode_does_not_block_the_same_text_from_a_vn_session(tmp_path):
    """The frozen-side dedupe must key on the full (query, skill, language) triple, like the in-run
    one, not on the query text.

    All 62 frozen rows were generated in en-mode, and since #69 a vn/mixed Session both filters on
    `language: "vi"` and embeds with a different model (e5). Keyed on text alone, the moment a
    string is frozen with `language: null` the identical string logged from a vn Session can never
    be harvested — so `--harvest`, the only mechanism for growing the set toward 150+, was
    structurally incapable of ever admitting the vn call shape. That is a different lookup, and it
    is the one whose ranking nobody has measured.
    """
    frozen = _case("f", query="drift monitoring", skill="mlops", language=None)
    (tmp_path / "a.md").write_text(
        "Concept lookup: `drift monitoring` (skill=`mlops`, language=`vi`) -> `x`\n"
        "Concept lookup: `drift monitoring` (skill=`mlops`, language=`any`) -> `x`\n",
        encoding="utf-8",
    )

    harvested = harvest_lookup_calls(tmp_path, known=(frozen,))

    assert [(h.query, h.skill, h.language) for h in harvested] == [("drift monitoring", "mlops", "vi")]


def test_harvest_dedupes_on_the_filters_not_on_the_query_text_alone(tmp_path):
    """The in-run half of the same rule. One string logged under three different filter shapes is
    three different lookups with three different candidate sets; collapsing them to one would drop
    two rows a human never got to see. The exact repeat is still collapsed."""
    (tmp_path / "a.md").write_text(
        "Concept lookup: `drift` (skill=`mlops`, language=`any`) -> `x`\n"
        "Concept lookup: `drift` (skill=`mlops`, language=`vi`) -> `x`\n"
        "Concept lookup: `drift` (skill=`ml_fundamentals`, language=`any`) -> `x`\n"
        "Concept lookup: `drift` (skill=`mlops`, language=`any`) -> `y`\n",
        encoding="utf-8",
    )

    harvested = harvest_lookup_calls(tmp_path)

    assert [(h.skill, h.language) for h in harvested] == [("mlops", None), ("mlops", "vi"), ("ml_fundamentals", None)]


def test_harvest_refuses_a_directory_that_does_not_exist(tmp_path):
    """`rglob` on a missing path yields nothing, so a typo'd export dir printed "nothing new to
    harvest: every logged query is already in the frozen set." and exited 0 — a success message that
    is affirmatively false. Silence has to be distinguishable from an empty scan."""
    with pytest.raises(FileNotFoundError, match="nothing to harvest"):
        harvest_lookup_calls(tmp_path / "typo")

    assert harvest_lookup_calls(tmp_path) == ()  # the control: a real but empty dir is still empty


def test_a_harvested_stub_round_trips_through_the_loader(tmp_path):
    """The stub is the human's editing surface, so it has to be a loadable row once `expected` is
    filled — otherwise the pending-file convention hands the reviewer a syntax error."""
    (tmp_path / "a.md").write_text(
        'Concept lookup: `a "quoted" query` (skill=`mlops`, language=`vi`) -> `x`\n', encoding="utf-8"
    )

    stubs = render_harvest_stubs(harvest_lookup_calls(tmp_path)).replace(
        "expected: []", "expected: [mlops_drift_monitoring]"
    )
    path = tmp_path / "labels.yaml"
    path.write_text(f"version: 1\n{stubs}", encoding="utf-8")

    (case,) = load_retrieval_labels(path)

    assert (case.query, case.skill, case.language, case.source) == ('a "quoted" query', "mlops", "vi", "live")


def test_harvest_stubs_are_unlabelled_and_never_written(tmp_path):
    """The structural anti-ratchet: the tool that computes the score cannot write the file it is
    graded against. Stubs go to stdout with `expected: []` for a human to label."""
    (tmp_path / "a.md").write_text(
        "Concept lookup: `some new query` (skill=`mlops`, language=`any`) -> `x`\n", encoding="utf-8"
    )
    before = labels_checksum(DEFAULT_LABELS_PATH)

    stubs = render_harvest_stubs(harvest_lookup_calls(tmp_path))

    assert "expected: []" in stubs
    assert "some new query" in stubs
    assert labels_checksum(DEFAULT_LABELS_PATH) == before


# --- the CLI's exit codes (the gate half) ---------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _cli():
    """Import `scripts/retrieval_eval.py` by path — `scripts/` is not a package (same idiom as
    `tests/test_serde_golden.py`)."""
    spec = importlib.util.spec_from_file_location("retrieval_eval_cli", _REPO_ROOT / "scripts" / "retrieval_eval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_cli_exits_non_zero_when_nothing_was_scored(monkeypatch, capsys):
    """A run in which every case was unservable printed "no labelled cases were scored — nothing to
    report" and still exited 0. The module already refuses `hits / max(1, n)` for exactly this
    reason — a vacuous green is not a measurement — but that rule stopped at the property boundary,
    and it is the exit code that a gate actually reads."""
    module = _cli()
    monkeypatch.setattr(module, "load_retrieval_labels", lambda: (_case("a", skill="no_such_shelf"),))

    assert module.main(store_kind="memory") == 1
    assert "nothing was measured" in capsys.readouterr().err


def test_the_cli_exits_zero_on_a_scored_report(monkeypatch, capsys):
    """The control: the same path with one servable, labelled case must still be green, or the
    check above would pass by making the script always fail."""
    module = _cli()
    monkeypatch.setattr(
        module,
        "load_retrieval_labels",
        lambda: (_case("a", query="drift monitoring", skill="mlops", expected=("mlops_drift_monitoring",)),),
    )

    assert module.main(store_kind="memory") == 0
    assert "hit@1: 1/1" in capsys.readouterr().out


def test_the_cli_exits_non_zero_when_the_harvest_directory_is_missing(tmp_path, capsys):
    """`--harvest` on a typo'd path reported success with a false message. It must be loud instead,
    and it must still be silent-and-green on a real directory that simply holds nothing new."""
    module = _cli()

    assert module.main(harvest=str(tmp_path / "typo")) == 1
    assert "cannot harvest" in capsys.readouterr().err

    assert module.main(harvest=str(tmp_path)) == 0
    assert "nothing new to harvest" in capsys.readouterr().out
