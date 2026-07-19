# Confidence-weighted evidence updates

**Type:** AFK
**Kind:** improvement

## What to build

`apply_evaluation` moves the Beta skill state at a fixed evidence weight regardless of the
Evaluator's `confidence` — a judgment that just had its confidence lowered by the
`weighted_score` cross-check (slice 0003), or that triggered Self-critique, still shifts mastery
exactly as much as a fully confident one. The system computes a trustworthiness signal and then
ignores it at the precise moment it matters: updating the state the Supervisor steers by.

Scale evidence weight by Evaluator confidence so shaky judgments move the posterior less. Keep it
pure Python inside the skill-state module (ADR 0002 — no LLM in the update path). This also
creates the seam that Panel Verdict (issue 0027) later replaces with agreement-derived weight on
escalated questions.

## Acceptance criteria

- [x] Evidence weight is a monotonic function of Evaluator confidence, documented where it is
      defined, with unit tests for the property: lower confidence ⇒ strictly smaller posterior
      shift, identical score
- [x] Full-confidence behavior stays at parity with today's fixed weight — no silent
      recalibration of what existing tests assert
- [x] The Markdown export shows the applied weight per evaluation, so the effect is auditable in
      a Session artifact
- [x] A degraded/failed question still applies zero evidence (unchanged prior), as issue 0014
      established

## Blocked by

None — can start immediately.

## Done

- Added `confidence_weight(confidence)` in `skill.py`: linear in confidence with a floor
  (`CONFIDENCE_WEIGHT_FLOOR = 0.25`), so it is strictly monotonic and returns exactly `EVIDENCE_WEIGHT`
  at `confidence == 1.0` (parity). `apply_evaluation` now passes `weight=confidence_weight(ev.confidence)`
  to `observe`, keeping the update pure-Python (ADR 0002).
- The applied weight is recorded per question — `_dump_micro_loop` stores
  `evidence_weight = confidence_weight(resolved.confidence)` (same function `apply_evaluation` uses, so
  it can't drift), and `_dump_failed_question` stores `0.0`. The exporter renders it on each question's
  resolved-score line.
- Degraded/failed questions are unchanged: the supervisor still skips `apply_evaluation` and keeps the
  prior, and the recorded weight is `0.0`.

## Verified

- `uv run pytest tests/test_skill.py -q` — 16 passed, including parity at full confidence, strict
  monotonicity, the floor (weak-not-zero), out-of-range clamping, and the core property (same score,
  lower confidence ⇒ strictly smaller posterior shift).
- `uv run pytest -q` — 174 passed (existing trajectory/supervisor thresholds intact — no silent
  recalibration), `ruff check` clean. The demo export asserts `evidence weight:` is present.

## Status

**Closed.** Acceptance criteria are implemented and covered.

## Continued by (2026-07-19 remediation)

- On the saturated judge the weight range collapsed to [1.93, 2.0] — the mechanism only bites through its deterministic caps. Replacement input: ADR 0011 derived confidence (Proposed); trigger rework: R-16 (GH #71).
