# Panel Verdict — cost-gated committee debrief

**Type:** AFK
**Kind:** enhancement

## What to build

When the Evaluator's own signals say a score is shaky — the existing Self-critique trigger
conditions (low confidence, `weighted_score` divergence) — escalate to a small committee instead
of a single re-read: a **Skeptic** pass and an **Advocate** pass (two role prompts, each citing
transcript evidence), after which the **Evaluator issues the final verdict having read both**.
ADR 0001's single-judge invariant holds: the panel *advises*, the Evaluator *decides*.

Panel agreement becomes information: map it to the evidence weight applied to the skill state
(replacing the confidence-derived weight from issue 0021 on escalated questions) so a score the
committee split on moves the Beta less. Append a **committee packet** to the Markdown export —
each voice's one-paragraph scorecard and the disagreement — the artifact a real hiring-committee
debrief produces.

Strictly cost-gated: with one free-tier provider, the panel runs *only* in the ambiguous band the
existing triggers already define — never on confident scores.

## Acceptance criteria

- [x] Panel runs only when the existing Self-critique trigger conditions fire; a test proves no
      escalation happens on confident scores (cost gate)
- [x] The Evaluator remains the sole verdict owner (ADR 0001); Skeptic/Advocate outputs are
      advisory and visible in the export's committee packet
- [x] Agreement → evidence-weight mapping is tested: disagreement produces a strictly smaller
      posterior shift than consensus at the same score
- [x] 2–3 bench cases (0022) measure whether the panel improves accuracy on borderline goldens;
      the result is recorded in `docs/audits/` either way

## Blocked by

- 0021 (the evidence-weight seam this replaces on escalated questions)
- 0022 (without the bench, "does debate help?" is unanswerable)

## Status

**Closed (2026-07-11).** Escalation now runs `_panel_opinion` (Skeptic, then Advocate — advisory
only, they never score dimensions) followed by the Evaluator's informed re-read via
`_build_panel_verdict_messages`; the verdict is kept unconditionally and carries a `PanelTrace`
(`SelfCritiqueTrace` remains readable for pre-0027 checkpoints). `skill.panel_agreement_weight`
maps committee disagreement (|skeptic − advocate|, 0–4) linearly onto the evidence weight with the
0021 floor, and `evidence_weight_for` is the single dispatch both `apply_evaluation` and the
transcript dump use. The export appends the committee packet (triggers, first pass → verdict,
disagreement, both scorecards).

Live: the 29-case bench is green — four borderline `panel_*` cases were added — and a
forced-escalation experiment (`scripts/experiment_issue_0027_forced_escalation.py`) answers the
"does debate help?" question honestly: the verdict never moved (and never left a band), committee
disagreement cleanly separates ambiguous from clear-cut cases (the actual value delivered, as the
evidence-weight signal), and natural escalations are 0/10 because gpt-5.4-mini's confidence is
saturated ≥0.90 — the trigger threshold belongs to the bench re-anchor worklist. Full narrative:
`docs/audits/calibration-bench-2026-07-11-panel-verdict.md` (baseline:
`calibration-bench-2026-07-11-panel-baseline.md`).
