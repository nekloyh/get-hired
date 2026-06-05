# Self-critique reflection

**Type:** AFK

## What to build

The evaluator-optimizer reflection step (see `ADR 0001`): **Self-critique** lives inside the Evaluator's micro-loop, not the Supervisor. When an evaluation's `confidence` is below threshold — including the low-confidence signal raised by the `weighted_score` cross-check guard (slice 0003) — re-evaluate the same exchange (e.g. with a critique of the first pass appended) and keep the more confident result. This produces a trustworthy score for the current question before control ever returns to the macro-loop.

## Acceptance criteria

### Implemented

- [x] A low-confidence evaluation triggers exactly one re-evaluation pass
- [x] A high-confidence evaluation does not trigger re-evaluation
- [x] The cross-check divergence from slice 0003 is one of the triggers
- [x] The result kept is the higher-confidence of the two passes, and the trigger + outcome are logged
- [x] Micro-loop transcript trace exposes the self-critique triggers for the turn that was judged

### Verified live

- [x] MiMo live Evaluator sanity check passes (`uv run pytest -m live -ra`, verified 2026-05-31)

## Blocked by

- 0005 (operates within the micro-loop)

## Status

**Closed.** Acceptance criteria are implemented and covered.
