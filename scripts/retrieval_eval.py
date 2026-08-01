"""Replay the FROZEN concept-retrieval eval set and report hit@1 with a Wilson 95% CI (R-15, #70).

Supersedes `scripts/review_issue_0008_chroma_retrieval.py` as the retrieval gate. That script
rebuilt its eval from `questions.yaml` on every run, so the bank's growth silently moved the
denominator (50 lookups at the 2026-07-11 audit, 59 at 184f5a2) and the labels could be — and were —
edited upward by the agent reading the score. Here the eval set is a frozen file this script can only
read: `data/bench/retrieval-labels.yaml`, whose sha256 is pinned by `tests/test_retrieval_eval.py`.

Per ADR 0009 addendum (c), this names its own gate: a retrieval change gates on THIS script, never on
`coach bench` (which measures the judge and would not notice a retrieval regression at all).

Run:
    uv run python scripts/retrieval_eval.py                     # the production path (Chroma + BGE)
    uv run python scripts/retrieval_eval.py --store memory      # explicit opt-in to the toy ranker
    uv run python scripts/retrieval_eval.py --harvest data/exports \
        > data/bench/pending-retrieval-queries-$(date +%F).yaml

Exits 2 with a clear message when the rag extras are missing (same convention as the script it
replaces); any other store failure propagates its traceback. `--harvest` prints YAML stubs to stdout
and writes nothing, ever: the
tool that computes the score must not be able to write the file it is graded against, and
`data/exports/` is Candidate transcript data a human must read before it becomes repo content.
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
        print(render_harvest_stubs(harvest_lookup_calls(harvest, known=cases)), end="")
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
