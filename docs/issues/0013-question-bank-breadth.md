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

### Breadth (done 2026-07-11)

- [x] Questions spanning all 5 Skills — **42 total** (9/9/9/9/6), every Skill spanning the full
      1–5 difficulty scale
- [x] Vietnamese-context questions tagged to the vietnamese_nlp Skill — **6** (word segmentation,
      diacritic restoration, PhoBERT, Unicode/tone normalization, teencode, Zalo-style chatbot)
- [x] Questions are reviewed for accuracy and difficulty calibration — review pass documented in
      `docs/audits/question-bank-review-2026-07-11.md` (AI-drafted + reviewed; human sign-off at
      PR review, flagged items listed there)

## Done (structural + first tranche)

- Migrated the bank to `src/interview_coach/data/questions.yaml` (+ `bank.py` loader with fail-loud
  validation). Extended `SeedQuestion` with `expected_concepts` and `follow_up_seeds`.
- Authored a first tranche of 15 questions (3 per Skill, including 3 Vietnamese-context items), each
  with a per-question weighted rubric that disables irrelevant dimensions with weight 0.
- `test_bank.py` asserts per-Skill coverage, `expected_concepts` resolution, weight-0 presence, and
  the fail-loud validation cases.

## Done (breadth tranche, 2026-07-11)

- Grew the bank 15 → 42 questions and the concept notes 14 → 40 (every new `expected_concepts`
  entry resolves; new notes double as issue 0008 breadth). Difficulty now spans 1–5 in every Skill,
  so `target_difficulty` extremes select genuinely different prompts.
- Breadth is pinned by tests: ≥40 total, ≥6 per Skill, ≥3 difficulty levels per Skill, ≥6
  Vietnamese questions, ≥6 `vi` notes.
- Full review: `docs/audits/question-bank-review-2026-07-11.md`.

## Blocked by

- 0005 (proves the question + rubric shape with the seed set)

## Status

**Closed.** Breadth target reached (42 ≥ 40), Vietnamese coverage at target (6), accuracy +
difficulty review documented. Further growth belongs to external packs (ADR 0008), not this issue.
