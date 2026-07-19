"""Concept-retrieval relevance review on the REAL Chroma store (issue 0008 follow-up).

The 2026-07-11 review pass (`docs/audits/concept-retrieval-review-2026-07-11.md`) ran on
`InMemoryConceptStore` because chromadb was not installed, making its 47/50 a *floor* with three
documented toy-ranker artifacts. This script repeats the exact same 50-lookup method against the
production path — `ChromaConceptStore` + `bge-small-en-v1.5` — so the two runs are directly
comparable, and re-runs the Vietnamese-note reachability probe.

Method (unchanged from the audit): every bank question's `follow_up_seeds` are the follow-up needs
the Interviewer would look up mid-session. Each seed, plus its question text (the context the
Interviewer has), goes through `lookup_concept` with the Skill filter applied; a lookup is a **hit**
when the returned note is one of that question's `expected_concepts` (hand-labelled ground truth).

Run: ``uv run python scripts/review_issue_0008_chroma_retrieval.py [--embedding-model ID]``
(prints a Markdown report to stdout; default embedder is bge-small-en-v1.5, pass
``--embedding-model intfloat/multilingual-e5-small`` for the multilingual A/B arm). Exits 2 with a
clear message when chromadb/sentence-transformers are not installed; exits 1 on store errors. The
embedder downloads on first use.
"""

from __future__ import annotations

import argparse

from interview_coach.bank import load_questions
from interview_coach.concepts import BGE_SMALL_EN, SEED_CONCEPTS, build_concept_store, lookup_concept


def main(embedding_model: str = BGE_SMALL_EN) -> int:
    try:
        store = build_concept_store("chroma", seed=True, embedding_model=embedding_model)
    except RuntimeError as err:
        print(f"skipped: {err}")
        return 2

    questions = load_questions()
    per_skill: dict[str, list[int]] = {}
    misses: list[dict] = []
    total = 0

    print("# Concept retrieval review — real Chroma store (issue 0008 follow-up)")
    print()
    print(f"Store: ChromaConceptStore + {embedding_model}; notes: {len(SEED_CONCEPTS)}.")
    print()
    for skill, seeds in sorted(questions.items()):
        for question in seeds:
            if not question.follow_up_seeds or not question.expected_concepts:
                continue
            for seed in question.follow_up_seeds:
                total += 1
                query = f"{seed} — {question.question}"
                lookup = lookup_concept(store, query, skill=skill)
                hit = lookup.note.id in question.expected_concepts
                per_skill.setdefault(skill, []).append(int(hit))
                if not hit:
                    misses.append(
                        {
                            "skill": skill,
                            "seed": seed,
                            "got": lookup.note.id,
                            "score": lookup.score,
                            "expected": question.expected_concepts,
                        }
                    )

    hits = sum(sum(v) for v in per_skill.values())
    print(f"## Results: {hits}/{total} hits ({hits / total:.0%})")
    print()
    print("| Skill | hits | misses |")
    print("| --- | ---: | ---: |")
    for skill in sorted(per_skill):
        h = sum(per_skill[skill])
        n = len(per_skill[skill])
        print(f"| {skill} | {h}/{n} | {n - h} |")
    print()
    if misses:
        print("### Misses")
        print()
        for m in misses:
            score = "n/a" if m["score"] is None else f"{m['score']:.3f}"
            print(
                f"- **{m['skill']}** seed *\"{m['seed']}\"* -> `{m['got']}` (score {score}); "
                f"expected one of `{', '.join(m['expected'])}`"
            )
        print()

    # Vietnamese-note reachability probe: each vi note queried by its own (Vietnamese) title under
    # the language filter — how far an English embedder carries fully-Vietnamese queries.
    vi_notes = [note for note in SEED_CONCEPTS if note.language == "vi"]
    print(f"## Vietnamese-note reachability probe ({len(vi_notes)} vi notes)")
    print()
    self_hits = 0
    for note in vi_notes:
        lookup = lookup_concept(store, note.title, skill=note.skill, language="vi")
        ok = lookup.note.id == note.id
        self_hits += int(ok)
        score = "n/a" if lookup.score is None else f"{lookup.score:.3f}"
        print(f"- `{note.id}` <- own title: {'HIT' if ok else f'MISS (got `{lookup.note.id}`)'} (score {score})")
    print()
    print(f"Self-retrieval: {self_hits}/{len(vi_notes)}.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--embedding-model",
        default=BGE_SMALL_EN,
        help="SentenceTransformer model id (e5-family ids get their query:/passage: prefixes applied).",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.embedding_model))
