# Longitudinal Skill Ledger — cross-Session Bayesian memory

**Type:** AFK
**Kind:** enhancement

## What to build

Sessions are one-shot: every run cold-starts priors, so the tool cannot show progress or adapt to
a returning Candidate — the difference between a mock and a training arc. Add a per-Candidate
**ledger**: when a Session completes, persist the final per-Skill Beta posteriors; when the same
Candidate starts the next Session, load them with exponential pseudo-count decay by days elapsed
and feed them through the Diagnostic's existing prior seam instead of cold-start. Render a
"since last session: mlops 0.35 → 0.62" delta block in the Markdown export and final report.

ADR 0006 fixes the mechanism: decayed Bayesian priors, not transcript RAG. The core is
offline-testable arithmetic on the existing Beta math — deliberately insulated from provider
quality. ADR 0002's invariants hold: priors stay weak enough that direct evidence dominates
within an answer or two, and Role criticality still never moves the prior mean.

## Acceptance criteria

- [ ] `coach session --candidate <id>` seeds priors from the ledger with decay; a first-ever
      Session behaves exactly as today (cold start)
- [ ] Decay math is unit-tested: older evidence counts strictly less; parameters and their
      rationale documented next to the code
- [ ] An end-to-end two-session fixture test asserts prior carryover *and* that fresh direct
      evidence still dominates the carried prior (ADR 0002 invariant)
- [ ] Export + final report show per-Skill before → after across Sessions
- [ ] A missing/corrupt ledger degrades to cold start with a logged warning — never a crash
- [ ] Web setup can pass the candidate id so the ledger works from the UI too

## Blocked by

- ADR 0006 (mechanism decision). Independent of the provider situation — can start immediately.

## Status

**Open.**
