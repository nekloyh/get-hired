# Question-bank breadth

**Type:** HITL

## What to build

Grow the question bank from the single-Skill seed set (slice 0005) into full coverage: at least 40 questions across all 7 Skills, each with a prompt, expected concepts, a per-question rubric (fixed 5-dimension vocabulary with weights, weight 0 to disable irrelevant dimensions), and follow-up seeds. Include ~6 Vietnamese-context items (PhoBERT, VnCoreNLP/word segmentation, Zalo-style tasks). HITL because question *quality* and rubric *weighting* require human domain judgment — this is what makes the tool genuinely useful, not just wired.

## Acceptance criteria

- [ ] ≥40 questions spanning all 7 Skills, hand-editable and diff-friendly
- [ ] Each question carries expected concepts, a weighted 5-dimension rubric, and follow-up seeds
- [ ] Irrelevant rubric dimensions are weighted 0 per question (a concept question isn't scored on mlops_awareness)
- [ ] ~6 Vietnamese-context questions are included and tagged to the vietnamese_nlp Skill
- [ ] Questions are reviewed for accuracy and difficulty calibration by a human

## Blocked by

- 0005 (proves the question + rubric shape with the seed set)
