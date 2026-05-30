# Self-critique reflection

**Type:** AFK

## What to build

The evaluator-optimizer reflection step (see `ADR 0001`): **Self-critique** lives inside the Evaluator's micro-loop, not the Supervisor. When an evaluation's `confidence` is below threshold — including the low-confidence signal raised by the `weighted_score` cross-check guard (slice 0003) — re-evaluate the same exchange (e.g. with a critique of the first pass appended) and keep the more confident result. This produces a trustworthy score for the current question before control ever returns to the macro-loop.

## Acceptance criteria

- [ ] A low-confidence evaluation triggers exactly one re-evaluation pass
- [ ] A high-confidence evaluation does not trigger re-evaluation
- [ ] The cross-check divergence from slice 0003 is one of the triggers
- [ ] The result kept is the higher-confidence of the two passes, and the trigger + outcome are logged

## Blocked by

- 0005 (operates within the micro-loop)
