# Session history + progress dashboard — surface the ledger

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#83](https://github.com/nekloyh/get-hired/issues/83) (R-28)

## What to build

The cross-session ledger already exists server-side (issue 0023: decayed Beta posteriors per
Candidate; `web_api.py` consumes it) but no UI shows it — the product's differentiator,
longitudinal skill state, is invisible to the one persona it serves. Build the presentation
surface:

- **Session list** — completed Sessions for the current Candidate, from the exports directory +
  checkpoint DB plus durable summary records (reuse the implemented R-08/#63 disk persistence).
- **Per-Skill timeline** — persist one versioned summary per completed Session, then render
  mastery/confidence trajectories from those snapshots. The current ledger keeps only the latest
  Candidate snapshot; it cannot supply a historical timeline by itself. Reuse the existing storage
  seam and record pack, difficulty, evidence count and judge version for honest comparisons.
- **Since-last-session deltas** — the state already carries `ledger_prior_mastery`, so the immediate
  delta can use that value; historical comparisons still require durable Session snapshots.
- Optionally, per-Session drill-down to the existing export markdown.

**Governance:** this is a *presentation & planning* surface under the ADR 0006 addendum
(2026-07-19) — it may show history and transcripts (**coaching memory**); nothing it renders may
flow back into Evaluator/Interviewer/Supervisor prompts. The prompt-construction tests that
enforce the boundary are part of this slice's DoD.

## Acceptance criteria

- [ ] Two completed Sessions for the same Candidate → dashboard lists both and shows the correct
      per-Skill delta, including unchanged or negative results (e2e); never require improvement.
- [ ] Timeline renders from real versioned Session-summary fixtures; latest-only legacy ledger
      entries do not fabricate history. Duplicate completion does not duplicate a snapshot.
- [ ] Restarting the server does not empty the session list (depends on R-08/#63).
- [ ] Prompt-construction tests assert no dashboard/history text enters the three probing agents'
      messages, nor Diagnostic inputs beyond the sanctioned decayed priors (ADR 0006).
- [ ] No internal-jargon copy on the dashboard (same rule as 0034).

## Blocked by

- [Implementation plan M2](README.md#m2--explain-and-measure-the-judge-and-the-loop): durable
  turn/effect identity, quality and trace gates before the M3 product milestone.
- Existing random Session IDs, shared-token/Origin checks and disk exports are implemented in
  this checkout; preserve them and verify their integration rather than treating them as missing.
- **Personal/trusted pilot:** accounts/Postgres are not prerequisites. Shared-token users share
  a trust boundary; Candidate IDs are not authorization and the dashboard must not imply privacy.
- **Public launch or private histories between Candidates:** M4 ownership authorization must
  cover list, detail, progress, export, resume and all writes before exposure.

## Status

**Open in the local plan; remote status not refreshed.** Reordered 2026-09-13 from Later/Wave 3
into [M3](README.md#m3--finish-the-repeat-practice-loop-personaltrusted-pilot). #83 remains the
tracker. The M3 quality gate includes the retry entry point, two-Session flow, truthful progress,
retention/restore, and a small usefulness review; broad reskin is not a prerequisite.
