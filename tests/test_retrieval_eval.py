from __future__ import annotations

import json

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


# --- Wilson interval (AC-b) ----------------------------------------------------------------------


def test_wilson_interval_matches_published_endpoints():
    """The killer cases. Wald/normal-approximation — the common wrong implementation — returns
    (0.0, 0.0) and (1.0, 1.0) here: a 10-sample result laundered as certainty. These endpoints also
    catch a z of 2 instead of 1.959964 and a dropped z^2/4n^2 term."""
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.27753), abs=1e-5)
    assert wilson_interval(10, 10) == pytest.approx((0.72247, 1.0), abs=1e-5)


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
