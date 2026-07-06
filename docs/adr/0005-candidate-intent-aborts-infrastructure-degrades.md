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
