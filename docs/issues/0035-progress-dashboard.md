# Session history + progress dashboard — surface the ledger

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#83](https://github.com/nekloyh/get-hired/issues/83) (R-28)

## What to build

The cross-session ledger already exists server-side (issue 0023: decayed Beta posteriors per
Candidate; `web_api.py` exposes it) but no UI shows it — the product's differentiator,
longitudinal skill state, is invisible to the one persona it serves. Build the presentation
surface:

- **Session list** — completed Sessions for the current Candidate, from the exports directory +
  checkpoint DB (needs R-08/#63 disk persistence so the list survives restarts).
- **Per-Skill timeline** — mastery/confidence trajectory from the ledger, one line per Skill.
- **Since-last-session deltas** — the state already carries `ledger_prior_mastery`, so "your
  mlops moved +0.12 since Tuesday" is a subtraction, not a schema change.
- Optionally, per-Session drill-down to the existing export markdown.

**Governance:** this is a *presentation & planning* surface under the ADR 0006 addendum
(2026-07-19) — it may show history and transcripts (**coaching memory**); nothing it renders may
flow back into Evaluator/Interviewer/Supervisor prompts. The prompt-construction tests that
enforce the boundary are part of this slice's DoD.

## Acceptance criteria

- [ ] Two completed Sessions for the same Candidate → dashboard lists both and shows a non-zero
      per-Skill delta (e2e).
- [ ] Ledger timeline renders from the real `.skill-ledger.json` schema (unit/vitest on a fixture
      ledger).
- [ ] Restarting the server does not empty the session list (depends on R-08/#63).
- [ ] Prompt-construction tests assert no dashboard/history text enters the three probing agents'
      messages (ADR 0006 addendum enforcement).
- [ ] No internal-jargon copy on the dashboard (same rule as 0034).

## Blocked by

- R-06/#61 (random session ids), R-07/#62 (auth) — without them "the current Candidate" is
  anyone's transcript; the dashboard must not widen the existing exposure.
- R-08/#63 (exports on disk).

## Status

**Open.** Spec'd 2026-07-19 from the panel review (frontend gap #3, market table-stakes) and the
ADR 0006 carve-out; scheduled Later (Wave 3).
