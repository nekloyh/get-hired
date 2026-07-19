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

- [x] `coach session --candidate <id>` seeds priors from the ledger with decay; a first-ever
      Session behaves exactly as today (cold start)
- [x] Decay math is unit-tested: older evidence counts strictly less; parameters and their
      rationale documented next to the code
- [x] An end-to-end two-session fixture test asserts prior carryover *and* that fresh direct
      evidence still dominates the carried prior (ADR 0002 invariant)
- [x] Export + final report show per-Skill before → after across Sessions
- [x] A missing/corrupt ledger degrades to cold start with a logged warning — never a crash
- [x] Web setup can pass the candidate id so the ledger works from the UI too

## Blocked by

- ADR 0006 (mechanism decision). Independent of the provider situation — can start immediately.

## Done

- New `ledger.py`: a JSON store mapping `candidate_id -> {completed_at, skills: {alpha, beta}}`.
  `save_posteriors` persists final posteriors on completion; `load_priors` returns a returning
  Candidate's carried priors (raw last-Session means for display + `decay_beta`-decayed means for the
  prior seam) or `None` for a first-ever/absent/corrupt ledger.
- `decay_beta` decays Beta pseudo-counts toward the neutral prior by `0.5 ** (days / half_life)`
  (`LEDGER_HALF_LIFE_DAYS = 30`), so older evidence is pulled toward mean 0.5 and counts strictly less
  — warmer than a stranger, still probed. Pure arithmetic, no LLM (ADR 0006).
- The decayed mean feeds the existing seam (`diagnostic._initial_mastery_means`); Role criticality
  still sets prior strength + evidence bar via `_seed_prior` (ADR 0002 — role never moves the mean).
- `coach session --candidate <id> [--ledger-db path]` loads/persists; `candidate_id` rides in
  `SessionState` so a resumed Session also persists. Web `start_session` accepts `candidate_id` and the
  React setup panel exposes a "Candidate id" field.
- Export gets a "Since Previous Session" before → after table and the terminal summary a "SINCE LAST
  SESSION" block, both only for a returning Candidate; cold start renders nothing.
- Missing/corrupt/malformed ledgers degrade to cold start with a logged warning; write failures never
  fail an otherwise-complete Session.

## Verified

- `uv run pytest tests/test_ledger.py -q` — 14 passed: decay identity/half-life/monotonicity/limit,
  round-trip + multi-candidate merge, missing/unknown/corrupt/malformed → cold start, empty-id no-op,
  the two-session carryover + fresh-evidence-dominates invariant, and the export delta block.
- `uv run pytest tests/test_web_api.py -q` — 8 passed, including an end-to-end two-Session run for one
  candidate through the real API (first cold, second carries `ledger_prior_mastery`).
- `uv run pytest -q` — 189 passed, `ruff check` clean (cold-start paths unchanged). Web: `vitest` 20
  passed, `tsc -b` clean.

## Status

**Closed.** Acceptance criteria are implemented and covered.

## Continued by (2026-07-19 remediation)

- Atomic writes + lock: R-10 (GH #65). The ledger's first presentation surface is slice 0035 / R-28 (GH #83), governed by the ADR 0006 addendum boundary.
