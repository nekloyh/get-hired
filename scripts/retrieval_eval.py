"""Replay the FROZEN concept-retrieval eval set and report hit@1 with a Wilson 95% CI (R-15, #70).

Supersedes `scripts/review_issue_0008_chroma_retrieval.py` as the retrieval gate. That script
rebuilt its eval from `questions.yaml` on every run, so the bank's growth silently moved the
denominator (50 lookups at the 2026-07-11 audit, 59 at 184f5a2) and the labels could be — and were —
edited upward by the agent reading the score. Here the eval set is a frozen file this script can only
read: `data/bench/retrieval-labels.yaml`, whose sha256 is pinned by `tests/test_retrieval_eval.py`.

WHICH BENCH THIS IS NOT. ADR 0009 addendum (c) is titled "the two-bench contract" and enumerates
exactly two: `coach bench` (the judge) and the replay bench (the loop). Retrieval is neither, so this
script does not claim (c)'s authority for a third gate. What it does take from (c) is (c)'s *rule* —
a change must name its gate up front, and "it passed a bench" without naming which one is not
evidence. `coach bench` cannot see a retrieval regression at all, so naming it for a retrieval change
would be exactly that empty claim; this script is what a retrieval change should be measured on, on
its own merits rather than on borrowed ADR standing.

Run:
    uv run python scripts/retrieval_eval.py                     # the production path (Chroma + BGE)
    uv run python scripts/retrieval_eval.py --store memory      # explicit opt-in to the toy ranker
    uv run python scripts/retrieval_eval.py --harvest data/exports \
        > data/bench/pending-retrieval-queries-$(date +%F).yaml

READ THIS BEFORE RUNNING THE FIRST LINE. `uv sync --dev` does NOT install the rag extras (chromadb +
sentence-transformers), so on a stock dev environment the default `--store chroma` prints
`skipped: ...` and exits 2 — it does not fall back. That is deliberate: `build_concept_store("auto")`
would degrade to the toy ranker with only a log warning, and an eval whose header names Chroma while
its numbers came from the toy ranker is worse than one that refuses to run. To get a hit@1 + CI you
must pick one, explicitly:
    uv sync --extra rag && uv run python scripts/retrieval_eval.py    # the production path
    uv run python scripts/retrieval_eval.py --store memory            # the toy ranker, named as such

Exit codes: 0 a scored report; 1 nothing was scored (every case unservable or unlabelled — a
vacuous green is not a pass) or a harvest that could not read its directory; 2 the store could not be
built. Any other store failure propagates its traceback.

`--harvest` prints YAML stubs to stdout and writes nothing, ever: the tool that computes the score
must not be able to write the file it is graded against, and `data/exports/` is Candidate transcript
data a human must read before it becomes repo content.
"""

from __future__ import annotations

import argparse
import sys

from interview_coach.concepts import BGE_SMALL_EN, build_concept_store, lookup_concept
from interview_coach.retrieval_eval import (
    DEFAULT_LABELS_PATH,
    evaluate_retrieval,
    harvest_lookup_calls,
    labels_checksum,
    load_retrieval_labels,
    render_harvest_stubs,
    render_retrieval_report,
    unknown_expected_concepts,
)


def main(store_kind: str = "chroma", embedding_model: str = BGE_SMALL_EN, harvest: str | None = None) -> int:
    cases = load_retrieval_labels()
    if harvest is not None:
        try:
            found = harvest_lookup_calls(harvest, known=cases)
        except FileNotFoundError as err:
            # A typo'd export dir must not print "nothing new to harvest" and exit 0: rglob on a
            # missing path yields nothing, so silence there is indistinguishable from success.
            print(f"cannot harvest: {err}", file=sys.stderr)
            return 1
        print(render_harvest_stubs(found), end="")
        return 0

    # Deliberately not `build_concept_store("auto")`: auto degrades to the toy ranker with only a log
    # warning, and an eval that silently measures a different path than the one in its header is
    # worse than an eval that refuses to run.
    try:
        store = build_concept_store(store_kind, seed=True, embedding_model=embedding_model)
    except RuntimeError as err:
        print(f"skipped: {err}")
        return 2

    report = evaluate_retrieval(
        cases, lambda query, skill, language: lookup_concept(store, query, skill=skill, language=language)
    )
    print(
        render_retrieval_report(
            report,
            store=store_kind,
            embedding_model="n/a" if store_kind == "memory" else embedding_model,
            checksum=labels_checksum(DEFAULT_LABELS_PATH),
        ),
        end="",
    )
    if stale := unknown_expected_concepts(cases):
        # Not a scoring failure but a labelling one: these rows can never hit, so the headline
        # number is understating retrieval until a human re-points or retires them.
        print(
            f"\nWARNING: {len(stale)} labelled concept id(s) are no longer on the shelf: {', '.join(stale)}",
            file=sys.stderr,
        )
    if report.n_scored == 0:
        # The exit-code half of the module's own rule against `hits / max(1, n)`. A run where every
        # case was unservable prints "nothing to report" and would otherwise still exit 0 — a merge
        # gate that goes green on having measured nothing is not a gate.
        print(
            f"FAILED: 0 of {len(cases)} frozen cases were scored — nothing was measured.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default="chroma", choices=("chroma", "memory"), help="concept store to measure")
    parser.add_argument(
        "--embedding-model",
        default=BGE_SMALL_EN,
        help="SentenceTransformer model id (e5-family ids get their query:/passage: prefixes applied).",
    )
    parser.add_argument(
        "--harvest",
        metavar="DIR",
        help="scan DIR for logged live lookups and print unlabelled YAML stubs to stdout (writes nothing).",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.store, args.embedding_model, args.harvest))
