# Two-level control hierarchy with a thin, plan-executing Supervisor

Control is split into two levels. The **Interviewer** owns the within-question micro-loop; the **Supervisor** owns the between-question macro-loop. The **Evaluator** is the single judge of answers — the Interviewer never scores, it only asks questions and generates follow-ups (with RAG tools) when the Evaluator's `follow_up_recommended` flag (an LLM judgment over the full exchange, framed around marginal information gain) asks for one. **Self-critique** on a low-confidence score happens *inside* the Evaluator's micro-loop, not as a Supervisor action, because re-checking a score is part of finishing the current question's judgment. The **Supervisor** is a plan-executor over the Diagnostic's Topic Plan whose only LLM call decides one thing: whether emerging skill-state evidence justifies *deviating* from the plan (extra question, skip ahead, switch skill, end early). Hard caps (max questions, max time) are deterministic rails.

## Considered Options

The V2 plan (`MVP_v2.md`) proposed an LLM Supervisor that routes *every* decision, including `deep_dive` and `self_critique`. We rejected it: `deep_dive` is a within-question concern (a Follow-up the Interviewer owns) and `self_critique` has an obvious deterministic trigger (low confidence → always re-check), so routing them through the Supervisor adds model calls to decide things that aren't genuinely ambiguous. Concentrating the LLM judgment on the single ambiguous decision (deviate-from-plan) is more reliable, cheaper, and easier to defend than "the supervisor is an LLM that decides everything."

## Amendment (2026-07-19). Status: Proposed — gated on experiments E1 and E4

**Not applied to code until this section's status is Accepted.** The two-level hierarchy and the
single-judge/asker split above were independently re-derived and stand. Two components of the
original argument did not survive re-derivation and are on trial:

1. **The premise "self_critique has an obvious deterministic trigger (low confidence)" is
   factually dead on the current judge.** gpt-5.4-mini self-reports confidence ≥0.90 on every
   bench case (20/20 in the [0.9, 1.0] bucket, mean 0.95 — audit 2026-07-11) and natural panel
   escalations are 0/10. The trigger the original text calls "obvious" never fires. The proposed
   replacement control vocabulary — **derived confidence** from measured disagreement — is ADR
   0011 (gated on E4/E5); if it is accepted, this ADR's trigger premise is amended to cite it.
2. **The LLM deviation call has never been shown to beat the deterministic policy.** Symptoms:
   its output needed a phrase-list validator to police (`supervisor.py:569`), and the
   deterministic fallback is better-tested than the call itself. **Experiment E1** (replay bench,
   issue 0029): 3 personas × 3 plan rotations × 2 arms (LLM deviation vs policy-only), judge held
   constant. *Win criteria for keeping the call:* strictly better on ≥1 of {posterior MAE vs
   persona ground truth, wasted probes on strong skills, deviation-changed-outcome count} and no
   worse on the others; otherwise the call is removed and the Supervisor becomes fully
   deterministic rails. Either outcome is recorded here with the numbers.

*Source: ADR red-team review 2026-07-19 — verdict AMEND (hierarchy reaffirmed; trigger premise
dead by measurement; deviation call unproven → E1).*
