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

- [x] Ctrl-D / closed stdin at any prompt aborts the Session with the designed exit code 2 and
      message; no failed questions are recorded and no further LLM calls are made
- [x] Infrastructure failures (provider/tool/schema errors) still isolate per-question exactly as
      issue 0014 designed — all existing failure-isolation tests keep passing
- [x] The CLI final summary prints the recorded error for genuinely failed questions
- [x] Graph-level tests cover both sides of the taxonomy: intent → abort, infrastructure → isolate

## Blocked by

- ADR 0005 (defines the exception taxonomy this implements)

## Done

- Added a `CandidateIntent` base class in `microloop.py`; `CandidateInputUnavailable` and
  `CandidateExhausted` now subclass it, so the classification lives on the exception taxonomy (ADR 0005).
- `question_node` re-raises `CandidateIntent` *before* the per-question `except Exception`
  failure-isolation net, so EOF/Ctrl-D and web cancel/disconnect abort the Session instead of being
  recorded as zero-evidence `failed` questions. Infrastructure errors still hit the isolate-and-advance net.
- The CLI now catches `CandidateIntent` (was `CandidateInputUnavailable`) → exit code 2, and the
  Session summary prints the recorded `error` for genuinely failed questions.

## Verified

- `uv run pytest` -> 165 passed. New graph-level `test_candidate_intent_aborts_session_and_is_not_recorded_as_failed`
  (intent -> abort, zero LLM calls, no failed question) and `test_session_summary_prints_recorded_error_for_failed_question`;
  the existing `test_question_failure_is_isolated_and_session_continues` still passes (infrastructure -> isolate).
- Real interactive-CLI smoke: a closed (EOF) stdin at the first prompt exits 2 with the designed
  message, records no failed questions, and prints no "complete" summary.

## Status

**Closed.** Acceptance criteria are implemented and covered.
