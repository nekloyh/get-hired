# weighted_score cross-check guard

**Type:** AFK

## What to build

Harden the Evaluator's LLM-emitted `weighted_score` with a deterministic consistency check. Compute the linear value in Python from the per-dimension scores and their weights, compare it to the number the LLM emitted, and when the two diverge beyond a threshold, lower the evaluation's `confidence` (which can later trip self-critique, slice 0006). The model agreeing with its own arithmetic becomes a free confidence signal; the gap between holistic judgment and mechanical sum is the alarm.

This keeps the holistic LLM `weighted_score` (so the model can apply non-linear judgment like capping a fatally wrong answer) while closing the hole where an inflated bottom-line quietly raises mastery despite weak per-dimension scores.

## Acceptance criteria

- [ ] Python computes the linear weighted score from dimension scores × weights
- [ ] When |LLM score − linear score| exceeds the threshold, confidence is reduced
- [ ] When they agree, confidence is unaffected
- [ ] An evaluation with low dimension scores but an inflated LLM `weighted_score` is caught (confidence drops)

## Blocked by

- 0001 (refines the evaluation output)
