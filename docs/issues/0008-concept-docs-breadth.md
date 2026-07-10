# Concept-docs breadth

**Type:** HITL

## What to build

Grow the `concepts` collection from the seed set into real coverage across the Skill taxonomy, so the Interviewer's `lookup_concept` has substance to retrieve. Concept notes are short, self-contained explanations (whole-document chunks). Source from curated material (e.g. ML interview/system-design references) plus a light set of Vietnamese-specific notes (PhoBERT, VnCoreNLP). This is HITL because concept *quality and accuracy* need human judgment, and the breadth is steered over time by which concepts real Candidate answers actually surface.

## Acceptance criteria

- [x] Concept coverage exists for each Skill in the taxonomy (≥2 notes per Skill; enforced by the loader)
- [x] Notes are short and self-contained (no chunk-splitting artifacts)
- [x] A light set of Vietnamese-specific concept notes is included (word-seg, PhoBERT, VnCoreNLP, diacritics)
- [x] Retrieval for a sampled set of follow-up needs returns relevant, accurate notes — review pass
      documented in `docs/audits/concept-retrieval-review-2026-07-11.md` (50 sampled lookups, 94%
      hit rate after review-driven label/tag fixes; human sign-off at PR review)

## Done (structural + first tranche)

- Migrated the concept notes to `src/interview_coach/data/concepts.yaml` (loaded + validated by
  `bank.py`; the loader requires ≥1 note per canonical Skill).
- Authored 14 notes spanning all 5 Skills (≥2 each), including 4 Vietnamese-language notes.

## Done (breadth + review pass, 2026-07-11)

- Breadth landed with issue 0013: 14 → **40 notes** (≥4 per Skill, 6 `vi`-language), each backing
  at least one question's `expected_concepts`.
- Retrieval relevance review: every question's `follow_up_seeds` (50 lookups) run through
  `lookup_concept` with Skill filtering — **47/50 return an expected-relevant note**. Four initial
  misses were label/metadata defects the review fixed (retrieval was right, the labels were
  stale); the 3 residual misses are toy-ranker artifacts documented in the report.
- All 40 notes read for technical accuracy; no content errors found.
- Non-blocking follow-up recorded in the report: re-run the same 50-lookup sample on the
  production Chroma + BGE path when it is stood up; consider a multilingual embedder if
  Vietnamese-query relevance should exceed what metadata routing already guarantees.

## Blocked by

- 0007 (the concepts mechanism + tool)

## Status

**Closed.** Coverage, self-containment, Vietnamese notes, and the retrieval relevance/accuracy
review are all done. Ongoing steering by real Candidate answers continues opportunistically (and
via external packs, ADR 0008), not as an open acceptance criterion.
