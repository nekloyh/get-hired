# Concept-docs breadth

**Type:** HITL

## What to build

Grow the `concepts` collection from the seed set into real coverage across the Skill taxonomy, so the Interviewer's `lookup_concept` has substance to retrieve. Concept notes are short, self-contained explanations (whole-document chunks). Source from curated material (e.g. ML interview/system-design references) plus a light set of Vietnamese-specific notes (PhoBERT, VnCoreNLP). This is HITL because concept *quality and accuracy* need human judgment, and the breadth is steered over time by which concepts real Candidate answers actually surface.

## Acceptance criteria

- [x] Concept coverage exists for each Skill in the taxonomy (≥2 notes per Skill; enforced by the loader)
- [x] Notes are short and self-contained (no chunk-splitting artifacts)
- [x] A light set of Vietnamese-specific concept notes is included (word-seg, PhoBERT, VnCoreNLP, diacritics)
- [ ] Retrieval for a sampled set of follow-up needs returns relevant, accurate notes (human-reviewed — ongoing HITL)

## Done (structural + first tranche)

- Migrated the concept notes to `src/interview_coach/data/concepts.yaml` (loaded + validated by
  `bank.py`; the loader requires ≥1 note per canonical Skill).
- Authored 14 notes spanning all 5 Skills (≥2 each), including 4 Vietnamese-language notes.
- Breadth beyond the first tranche, and human accuracy review of retrieval relevance, remain the
  ongoing HITL tail (steered by which concepts real Candidate answers surface).

## Blocked by

- 0007 (the concepts mechanism + tool)
