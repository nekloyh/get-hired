# Rejection post-mortem agent

**Type:** AFK
**Kind:** enhancement

## What to build

The entire interview-tool market is pre-interview practice or in-interview assistance; nobody
serves the post-rejection moment, where the strongest learning signal of a job search lives —
and where companies give candidates nothing. `coach postmortem`: an elicitation agent
interviews the Candidate *about a real interview they just had* — 5–8 adaptive clarifying
questions (what was asked, where the interviewer pushed back, when the energy shifted) — and
reconstructs the scorecard the company won't share:

- Convert messy recollection into a **typed reconstructed evaluation** per probed Skill, each
  with an explicit confidence reflecting that this is second-hand evidence.
- Fuse it into the Skill Ledger at **reduced evidence weight** (the sanctioned
  `observe(weight=...)` seam — roughly half normal weight; document the ratio).
- Regenerate the Study Plan and show a **before/after diff**: what this real-world data point
  changed.

The new agentic pattern here is a true human-in-the-loop elicitation loop: agent-led questioning
over unreliable human memory, converted into typed, weighted evidence for persistent Bayesian
state — something the fixture pipeline never exercises.

## Acceptance criteria

- [ ] `coach postmortem` completes an adaptive elicitation dialogue and emits a typed
      reconstructed evaluation per probed Skill with explicit confidence
- [ ] The ledger applies it at a reduced, documented evidence weight; the Study Plan regenerates
      with a visible before/after delta
- [ ] User abort mid-elicitation is handled as intent per ADR 0005 — clean exit, partial data
      either discarded or saved explicitly, never silently fabricated into evidence
- [ ] Offline fixture test covers the recollection → typed-evidence conversion end-to-end

## Blocked by

- 0018 (intent-abort handling this flow depends on)
- 0023 (the ledger it writes into)

## Status

**Open.**
