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

- [ ] Evidence weight is a monotonic function of Evaluator confidence, documented where it is
      defined, with unit tests for the property: lower confidence ⇒ strictly smaller posterior
      shift, identical score
- [ ] Full-confidence behavior stays at parity with today's fixed weight — no silent
      recalibration of what existing tests assert
- [ ] The Markdown export shows the applied weight per evaluation, so the effect is auditable in
      a Session artifact
- [ ] A degraded/failed question still applies zero evidence (unchanged prior), as issue 0014
      established

## Blocked by

None — can start immediately.

## Status

**Open.**
