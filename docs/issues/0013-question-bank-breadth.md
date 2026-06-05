# Question-bank breadth

**Type:** HITL

## What to build

Grow the question bank from the single-Skill seed set (slice 0005) into full coverage: at least 40 questions across all 5 Skills, each with a prompt, expected concepts, a per-question rubric (fixed 5-dimension vocabulary with weights, weight 0 to disable irrelevant dimensions), and follow-up seeds. Include ~6 Vietnamese-context items (PhoBERT, VnCoreNLP/word segmentation, Zalo-style tasks). HITL because question *quality* and rubric *weighting* require human domain judgment — this is what makes the tool genuinely useful, not just wired.

(Taxonomy is 5 Skills: `ml_fundamentals, deep_learning, mlops, system_design, vietnamese_nlp` — the V1 plan's `nlp`/`cv` were dropped.)

## Acceptance criteria

### Structural (done)

- [x] Each question carries expected concepts, a weighted 5-dimension rubric, and follow-up seeds
- [x] Irrelevant rubric dimensions are weighted 0 per question (a concept question isn't scored on mlops_awareness)
- [x] The bank is hand-editable and diff-friendly (`data/questions.yaml`, loaded + validated by `bank.py`)

### Breadth (ongoing HITL tail)

- [~] Questions spanning all 5 Skills — 15 now (3 per Skill, first tranche); ≥40 is the ongoing tail
- [~] Vietnamese-context questions tagged to the vietnamese_nlp Skill — 3 now (target ~6 as breadth grows)
- [ ] Questions are reviewed for accuracy and difficulty calibration by a human

## Done (structural + first tranche)

- Migrated the bank to `src/interview_coach/data/questions.yaml` (+ `bank.py` loader with fail-loud
  validation). Extended `SeedQuestion` with `expected_concepts` and `follow_up_seeds`.
- Authored a first tranche of 15 questions (3 per Skill, including 3 Vietnamese-context items), each
  with a per-question weighted rubric that disables irrelevant dimensions with weight 0.
- `test_bank.py` asserts per-Skill coverage, `expected_concepts` resolution, weight-0 presence, and
  the fail-loud validation cases.

## Blocked by

- 0005 (proves the question + rubric shape with the seed set)

## Status

**Open.** Structural work and the first tranche are implemented, but the target breadth and
human calibration review remain explicit HITL acceptance criteria.
