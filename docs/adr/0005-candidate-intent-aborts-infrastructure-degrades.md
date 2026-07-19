# Candidate intent aborts; infrastructure degrades

Exceptions crossing the orchestration boundary are classified into two kinds with opposite
handling. **Candidate-intent signals** — EOF/Ctrl-D on stdin, a web cancel or disconnect
(`CandidateInputUnavailable`, `CandidateExhausted`) — must propagate *out of* every
failure-isolation net and abort or suspend the Session, because that is what the Candidate asked
for. **Infrastructure failures** — provider transport errors, tool errors, schema-invalid model
output — are the only exceptions eligible for the per-question record-`failed`-and-advance net
(issue 0014) or a degrade path. Cancellation is modeled as a typed control signal (a distinct
sentinel object checked by the Candidate implementation), never as data (an empty-string answer).

## Why

Issue 0014's `except Exception` in `question_node` was written to survive a flaky provider, but it
also catches the Candidate saying "stop": a closed stdin turns an aborted interactive Session into a
cascade of zero-evidence `failed` questions ending in exit code 0, a Study Plan generated from
nothing, and ~6 wasted LLM calls — and the web layer's `""` disconnect sentinel gets consumed as a
real answer, so the Evaluator scores an empty reply and drags the Beta skill state down into a
checkpoint. Both variants were confirmed by direct code trace in the 2026-07 stability audit.

The blast-radius rule that resolves it: **infrastructure noise must never corrupt skill evidence,
and human intent must never be converted into fake evidence.** Failure isolation exists to protect
the Session *from the provider*, not to overrule the person in it.

## Considered Options

Keeping the broad net and special-casing the CLI handler was rejected: the same intent signals
arrive from two transports (terminal, WebSocket) and future ones (issue 0026's elicitation flow),
so the classification belongs at the exception taxonomy, not at each call site.

## Addendum (2026-07-19): a third category — budget exhaustion is anticipated scarcity

The dichotomy above classifies by "who asked for this outcome": the human (respect it) or the
infrastructure (contain it). Free-tier operation surfaced a case that is neither: **the daily token
budget running out mid-Session**. It is not Candidate intent, and it is not a surprise — the
reset schedule is known (00:00 UTC) and the ledger (issue 0021-era `usage.py`, shipped in PR #89)
counts down to it all day.

Correct handling is therefore its own category, **suspend-and-resume**:

- Never record-`failed`-and-advance: a budget stop is not evidence about the Candidate, and the
  0014 net converting it into zero-evidence `failed` questions is exactly the fake-evidence
  corruption this ADR forbids.
- Never a plain abort: the Candidate did not ask to stop, and checkpoint/resume — which already
  exists — makes a clean suspend nearly free.
- The Session suspends with an explicit, user-visible reason and offers resume once the budget
  resets; an `insufficient_quota`-class provider error is the *detection* half (treated as
  terminal, not retried — PR #89), this addendum states the *session-behavior* half.

Implementation is issue R-25 (GH #80): per-session budget, refuse-to-start into an empty budget,
mid-session breach → visible suspend, never a silent stall.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM + AMEND (third category); panel report
UX-risk #2 (quota blindness).*
