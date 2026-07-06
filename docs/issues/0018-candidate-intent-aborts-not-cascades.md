# Candidate-intent exceptions abort the Session instead of cascading

**Type:** AFK
**Kind:** bug

## What to build

Issue 0014's per-question failure isolation uses a broad `except Exception` in `question_node`
that also catches `CandidateInputUnavailable`/`CandidateExhausted` — the Candidate's own abort
signals. Confirmed trigger: run `coach session` interactively with stdin closed or press Ctrl-D at
the first prompt. Each question instantly "fails" and the Session advances, prompting and EOF-ing
again, until the max-questions rail ends it: exit code 0, a "complete" Session of zero-evidence
failed questions, a Study Plan generated from nothing, and ~6 wasted LLM calls. The designed
handler (exit code 2, "run in a terminal or pass --scripted") is now dead code because the
exception can only be raised inside the graph.

Narrow the net per ADR 0005: candidate-intent exceptions propagate out of the failure-isolation
net and abort cleanly; only infrastructure failures stay eligible for record-failed-and-advance.
While in the area: the CLI final summary currently shows only `stop=failed` for a failed question
— print the recorded error string so the reason is visible without opening the export.

## Acceptance criteria

- [ ] Ctrl-D / closed stdin at any prompt aborts the Session with the designed exit code 2 and
      message; no failed questions are recorded and no further LLM calls are made
- [ ] Infrastructure failures (provider/tool/schema errors) still isolate per-question exactly as
      issue 0014 designed — all existing failure-isolation tests keep passing
- [ ] The CLI final summary prints the recorded error for genuinely failed questions
- [ ] Graph-level tests cover both sides of the taxonomy: intent → abort, infrastructure → isolate

## Blocked by

- ADR 0005 (defines the exception taxonomy this implements)

## Status

**Open.**
