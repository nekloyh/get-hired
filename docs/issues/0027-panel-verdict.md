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

- [ ] Panel runs only when the existing Self-critique trigger conditions fire; a test proves no
      escalation happens on confident scores (cost gate)
- [ ] The Evaluator remains the sole verdict owner (ADR 0001); Skeptic/Advocate outputs are
      advisory and visible in the export's committee packet
- [ ] Agreement → evidence-weight mapping is tested: disagreement produces a strictly smaller
      posterior shift than consensus at the same score
- [ ] 2–3 bench cases (0022) measure whether the panel improves accuracy on borderline goldens;
      the result is recorded in `docs/audits/` either way

## Blocked by

- 0021 (the evidence-weight seam this replaces on escalated questions)
- 0022 (without the bench, "does debate help?" is unanswerable)

## Status

**Open.**
