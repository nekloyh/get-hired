# Concept-docs breadth

**Type:** HITL

## What to build

Grow the `concepts` collection from the seed set into real coverage across the Skill taxonomy, so the Interviewer's `lookup_concept` has substance to retrieve. Concept notes are short, self-contained explanations (whole-document chunks). Source from curated material (e.g. ML interview/system-design references) plus a light set of Vietnamese-specific notes (PhoBERT, VnCoreNLP). This is HITL because concept *quality and accuracy* need human judgment, and the breadth is steered over time by which concepts real Candidate answers actually surface.

## Acceptance criteria

- [ ] Concept coverage exists for each Skill in the taxonomy
- [ ] Notes are short and self-contained (no chunk-splitting artifacts)
- [ ] A light set of Vietnamese-specific concept notes is included
- [ ] Retrieval for a sampled set of follow-up needs returns relevant, accurate notes (human-reviewed)

## Blocked by

- 0007 (the concepts mechanism + tool)
